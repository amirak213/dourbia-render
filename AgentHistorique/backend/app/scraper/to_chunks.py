from __future__ import annotations

from decimal import Decimal

from app.rag.chunker import ChunkDraft, DocumentChunker, GeneratedDocument
from app.scraper.sources_config import ScrapeSource

# Reserved source_id range for scraped content, agreed with Amira: 90000+.
# Chosen to never collide with monument/circuit IDs (small decimals like 3.9).
SCRAPED_SOURCE_ID_BASE = Decimal("90000")

# Stable mapping: source.id -> synthetic source_id. Order matters (append-only)
# so re-running the scraper reuses the same IDs instead of duplicating rows.
# If you add a new ScrapeSource, add it to sources_config.py; its position in
# TRUSTED_SOURCES determines its offset here automatically.


def synthetic_source_id(source: ScrapeSource, all_sources: tuple[ScrapeSource, ...]) -> Decimal:
    try:
        offset = next(i for i, s in enumerate(all_sources) if s.id == source.id)
    except StopIteration as exc:
        raise ValueError(f"Unknown source id: {source.id}") from exc
    return SCRAPED_SOURCE_ID_BASE + Decimal(offset)


def build_generated_document(
    source: ScrapeSource,
    extracted_text: str,
    all_sources: tuple[ScrapeSource, ...],
    *,
    scraped_at_epoch: float,
) -> GeneratedDocument:
    return GeneratedDocument(
        source_type="scraped",
        source_id=synthetic_source_id(source, all_sources),
        title=source.name,
        language=source.language,
        text=extracted_text,
        metadata={
            "source_slug": source.id,
            "source_url": source.url,
            "topics": list(source.topics),
            "reliability": source.reliability,
            "priority": source.priority,
            "scraped_at_epoch": scraped_at_epoch,
        },
    )


def chunk_scraped_document(
    document: GeneratedDocument,
    *,
    chunk_size: int = 1500,
    overlap: int = 150,
) -> list[ChunkDraft]:
    # NOTE: overlap=150 here (vs. the project default of 0) — scraped
    # encyclopedic text tends to pack facts densely, and today we haven't
    # yet upgraded the chunker to be structure-aware. A small overlap
    # reduces the chance of splitting a fact (date, name) across a chunk
    # boundary. Revisit once the semantic chunker improvement lands.
    chunker = DocumentChunker(chunk_size=chunk_size, overlap=overlap)
    return chunker.chunk(document)
