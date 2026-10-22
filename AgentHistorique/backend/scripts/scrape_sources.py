"""Scrape trusted historical sources and insert chunks into document_chunks.

Batch, one-off run (not scheduled). Inserts chunks with embedding=None —
run `python scripts/generate_embeddings.py` afterwards to fill them in,
exactly like the existing Excel ingestion flow.

Run from backend/:
    python scripts/scrape_sources.py
    python scripts/scrape_sources.py --max-priority 1
    python scripts/scrape_sources.py --source-id britannica_carthage
    python scripts/scrape_sources.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.models.document_chunk import DocumentChunk
from app.scraper.extract import ExtractionError, extract_text
from app.scraper.fetch import FetchError, RespectfulFetcher
from app.scraper.sources_config import NOT_AUTO_SCRAPED_IDS, TRUSTED_SOURCES, ScrapeSource
from app.scraper.to_chunks import (
    build_generated_document,
    chunk_scraped_document,
    synthetic_source_id,
)
from app.scraper.wikipedia_api import fetch_wikipedia_extract

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-priority",
        type=int,
        default=3,
        help="Only scrape sources with priority <= this value (default: 3, all).",
    )
    parser.add_argument(
        "--source-id",
        type=str,
        default=None,
        help="Scrape a single source by its ScrapeSource.id (for testing/re-runs).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and extract but do not write to the database.",
    )
    parser.add_argument(
        "--include-blocked",
        action="store_true",
        help=(
            "Also attempt sources listed in NOT_AUTO_SCRAPED_IDS "
            "(robots.txt-blocked or anti-bot-protected). Off by default — "
            "these should normally be filled in manually, not force-fetched."
        ),
    )
    return parser.parse_args()


def select_sources(args: argparse.Namespace) -> list[ScrapeSource]:
    if args.source_id:
        match = next((s for s in TRUSTED_SOURCES if s.id == args.source_id), None)
        if match is None:
            raise SystemExit(f"Unknown --source-id: {args.source_id}")
        if match.id in NOT_AUTO_SCRAPED_IDS and not args.include_blocked:
            raise SystemExit(
                f"{args.source_id} is in NOT_AUTO_SCRAPED_IDS "
                "(robots.txt or anti-bot block) — pass --include-blocked to force it."
            )
        return [match]
    return [
        s
        for s in TRUSTED_SOURCES
        if s.priority <= args.max_priority
        and (args.include_blocked or s.id not in NOT_AUTO_SCRAPED_IDS)
    ]


def replace_chunks_for_source(session: Session, source: ScrapeSource) -> None:
    """Delete any existing chunks for this source before re-inserting.

    Makes the script idempotent: re-running it updates content instead of
    duplicating rows, as long as the source's position in TRUSTED_SOURCES
    (and therefore its synthetic source_id) hasn't changed.
    """
    source_id = synthetic_source_id(source, TRUSTED_SOURCES)
    session.execute(
        delete(DocumentChunk).where(
            DocumentChunk.source_type == "scraped",
            DocumentChunk.source_id == source_id,
        )
    )


def scrape_one(fetcher: RespectfulFetcher, source: ScrapeSource) -> str:
    if source.source_kind == "wikipedia_api":
        logger.info(
            "Fetching source=%s via Wikipedia API (title=%s)",
            source.id,
            source.wikipedia_title,
        )
        return fetch_wikipedia_extract(source)

    logger.info("Fetching source=%s url=%s", source.id, source.url)
    result = fetcher.fetch(source.url)
    logger.info("Extracting text for source=%s", source.id)
    return extract_text(result.html, source)


def main() -> None:
    configure_logging()
    args = parse_args()
    sources = select_sources(args)

    if not sources:
        logger.info("No sources matched the given filters. Nothing to do.")
        return

    logger.info("Scraping %s source(s): %s", len(sources), [s.id for s in sources])
    fetcher = RespectfulFetcher()

    session = SessionLocal() if not args.dry_run else None
    succeeded = 0
    failed: list[tuple[str, str]] = []

    try:
        for source in sources:
            try:
                text = scrape_one(fetcher, source)
            except (FetchError, ExtractionError) as exc:
                logger.error("Skipping source=%s: %s", source.id, exc)
                failed.append((source.id, str(exc)))
                continue

            document = build_generated_document(
                source,
                text,
                TRUSTED_SOURCES,
                scraped_at_epoch=time.time(),
            )
            chunk_drafts = chunk_scraped_document(document)
            logger.info(
                "source=%s -> %s chars extracted -> %s chunk(s)",
                source.id,
                len(text),
                len(chunk_drafts),
            )

            if args.dry_run:
                for draft in chunk_drafts:
                    logger.info(
                        "[dry-run] would insert chunk_index=%s len=%s preview=%r",
                        draft.metadata_json.get("chunk_index"),
                        len(draft.chunk_text),
                        draft.chunk_text[:120],
                    )
                succeeded += 1
                continue

            assert session is not None
            replace_chunks_for_source(session, source)
            for draft in chunk_drafts:
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
            session.commit()
            succeeded += 1

    finally:
        if session is not None:
            session.close()

    logger.info(
        "Scraping summary: succeeded=%s/%s failed=%s",
        succeeded,
        len(sources),
        len(failed),
    )
    for source_id, error in failed:
        logger.info("  - %s: %s", source_id, error)

    if not args.dry_run and succeeded:
        logger.info(
            "Next step: run `python scripts/generate_embeddings.py` to embed the new chunks."
        )


if __name__ == "__main__":
    main()
