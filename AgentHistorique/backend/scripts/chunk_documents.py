"""Chunk generated RAG documents and store them in document_chunks.

Run from backend/:
    python scripts/chunk_documents.py
    python scripts/chunk_documents.py --input ../data/processed/rag_documents.json
    python scripts/chunk_documents.py --chunk-size 1500 --overlap 100 --clear
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.models.document_chunk import DocumentChunk
from app.rag.chunker import ChunkDraft, DocumentChunker, GeneratedDocument
from app.rag.document_builder import build_all_documents, load_documents_from_json

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOCUMENTS_PATH = PROJECT_ROOT / "data" / "processed" / "rag_documents.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chunk RAG documents into document_chunks.")
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Path to generated documents JSON. If omitted, documents are built from PostgreSQL.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1500,
        help="Maximum chunk size in characters (default: 1500).",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=0,
        help="Character overlap between consecutive chunks (default: 0).",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete all existing document_chunks before inserting new ones.",
    )
    return parser.parse_args()


def load_documents(input_path: Path | None) -> list[GeneratedDocument]:
    if input_path is not None:
        if not input_path.exists():
            raise FileNotFoundError(f"Documents file not found: {input_path}")
        return load_documents_from_json(input_path)

    if DEFAULT_DOCUMENTS_PATH.exists():
        return load_documents_from_json(DEFAULT_DOCUMENTS_PATH)

    session = SessionLocal()
    try:
        return build_all_documents(session)
    finally:
        session.close()


def clear_chunks(session: Session) -> int:
    result = session.execute(delete(DocumentChunk))
    session.commit()
    return result.rowcount or 0


def replace_chunks_for_source(
    session: Session,
    source_type: str,
    source_id: Decimal,
    drafts: list[ChunkDraft],
) -> None:
    session.execute(
        delete(DocumentChunk).where(
            DocumentChunk.source_type == source_type,
            DocumentChunk.source_id == source_id,
        )
    )
    for draft in drafts:
        session.add(
            DocumentChunk(
                source_type=draft.source_type,
                source_id=draft.source_id,
                title=draft.title,
                language=draft.language,
                chunk_text=draft.chunk_text,
                metadata_json=draft.metadata_json,
                embedding=None,
            )
        )


def store_chunks(session: Session, drafts: list[ChunkDraft], clear_all: bool) -> None:
    if clear_all:
        clear_chunks(session)

    grouped: dict[tuple[str, Decimal], list[ChunkDraft]] = {}
    for draft in drafts:
        key = (draft.source_type, draft.source_id)
        grouped.setdefault(key, []).append(draft)

    for (source_type, source_id), source_drafts in grouped.items():
        replace_chunks_for_source(session, source_type, source_id, source_drafts)

    session.commit()


def print_summary(
    documents: list[GeneratedDocument],
    drafts: list[ChunkDraft],
    deleted_count: int,
) -> None:
    document_counts = Counter(document.source_type for document in documents)
    chunk_counts = Counter(draft.source_type for draft in drafts)
    multi_chunk_sources = Counter(
        (draft.source_type, draft.source_id)
        for draft in drafts
        if draft.metadata_json.get("chunk_count", 1) > 1
    )

    print("Chunking summary")
    print(f"  Documents read: {len(documents)}")
    print(f"  Monuments: {document_counts.get('monument', 0)}")
    print(f"  Circuits: {document_counts.get('circuit', 0)}")
    print(f"  Chunks created: {len(drafts)}")
    print(f"  Monument chunks: {chunk_counts.get('monument', 0)}")
    print(f"  Circuit chunks: {chunk_counts.get('circuit', 0)}")
    print(f"  Sources split into multiple chunks: {len(multi_chunk_sources)}")
    if deleted_count:
        print(f"  Existing chunks deleted: {deleted_count}")


def main() -> None:
    args = parse_args()
    documents = load_documents(args.input)
    chunker = DocumentChunker(chunk_size=args.chunk_size, overlap=args.overlap)
    drafts = chunker.chunk_many(documents)

    session = SessionLocal()
    deleted_count = 0
    try:
        if args.clear:
            deleted_count = clear_chunks(session)
        store_chunks(session, drafts, clear_all=False)
    finally:
        session.close()

    print_summary(documents, drafts, deleted_count)


if __name__ == "__main__":
    main()
