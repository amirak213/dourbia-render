"""Generate embeddings for document_chunks and store them in pgvector.

Run from backend/:
    python scripts/generate_embeddings.py
    python scripts/generate_embeddings.py --batch-size 16
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import SessionLocal
from app.models.document_chunk import DocumentChunk
from app.rag.embeddings import create_embedding_provider, validate_embedding_dimension

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate embeddings for document_chunks without embeddings.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Number of chunks to embed per batch (default: EMBEDDING_BATCH_SIZE from settings).",
    )
    return parser.parse_args()


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def count_pending_chunks(session: Session) -> int:
    return session.scalar(
        select(func.count())
        .select_from(DocumentChunk)
        .where(DocumentChunk.embedding.is_(None))
    ) or 0


def fetch_pending_chunk_ids(session: Session) -> list[int]:
    return list(
        session.scalars(
            select(DocumentChunk.id)
            .where(DocumentChunk.embedding.is_(None))
            .order_by(DocumentChunk.id)
        ).all()
    )


def load_chunks_by_ids(session: Session, chunk_ids: list[int]) -> list[DocumentChunk]:
    chunks = session.scalars(
        select(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids)).order_by(DocumentChunk.id)
    ).all()
    chunk_by_id = {chunk.id: chunk for chunk in chunks}
    return [chunk_by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in chunk_by_id]


def embed_pending_chunks(session: Session, batch_size: int) -> tuple[int, int]:
    pending_ids = fetch_pending_chunk_ids(session)
    total_pending = len(pending_ids)
    if total_pending == 0:
        logger.info("No chunks without embeddings. Nothing to do.")
        return 0, 0

    provider = create_embedding_provider()
    validate_embedding_dimension(provider)

    logger.info(
        "Starting embedding generation with model=%s dimension=%s batch_size=%s pending=%s",
        provider.model_name,
        provider.dimension,
        batch_size,
        total_pending,
    )

    embedded_count = 0
    for start in range(0, total_pending, batch_size):
        batch_ids = pending_ids[start : start + batch_size]
        batch = load_chunks_by_ids(session, batch_ids)
        texts = [chunk.chunk_text for chunk in batch]

        vectors = provider.embed_documents(texts)
        if len(vectors) != len(batch):
            raise RuntimeError(
                f"Embedding provider returned {len(vectors)} vectors for {len(batch)} texts"
            )

        for chunk, vector in zip(batch, vectors, strict=True):
            chunk.embedding = vector

        session.commit()
        embedded_count += len(batch)
        logger.info("Embedded %s/%s chunks", embedded_count, total_pending)

    return embedded_count, total_pending


def main() -> None:
    configure_logging()
    args = parse_args()
    settings = get_settings()
    batch_size = args.batch_size or settings.embedding_batch_size

    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    session = SessionLocal()
    try:
        pending_before = count_pending_chunks(session)
        embedded_count, total_pending = embed_pending_chunks(session, batch_size)
        pending_after = count_pending_chunks(session)
    finally:
        session.close()

    logger.info(
        "Embedding summary: embedded=%s processed=%s remaining=%s",
        embedded_count,
        total_pending,
        pending_after,
    )

    if pending_before and embedded_count == 0:
        raise RuntimeError("Expected to embed chunks but none were processed")


if __name__ == "__main__":
    main()
