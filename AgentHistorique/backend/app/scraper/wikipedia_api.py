"""Fetch article content from Wikipedia's official action API instead of
scraping HTML. Wikimedia has tightened bot-traffic enforcement in 2026
(see phabricator T400119) and now 403s many HTML scraping attempts even
with a compliant User-Agent. The action API is the intended programmatic
access path and is not subject to the same block.
"""

from __future__ import annotations

import logging
import time

import httpx

from app.scraper.fetch import USER_AGENT
from app.scraper.sources_config import ScrapeSource

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 15.0
_MIN_DELAY_SECONDS = (
    1.0  # politeness delay between requests, per Wikimedia's robot policy
)

_last_request_at: float = 0.0


class WikipediaApiError(RuntimeError):
    """Raised when the Wikipedia action API fails or returns no extract."""


def _respect_rate_limit() -> None:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < _MIN_DELAY_SECONDS:
        time.sleep(_MIN_DELAY_SECONDS - elapsed)
    _last_request_at = time.monotonic()


def fetch_wikipedia_extract(source: ScrapeSource) -> str:
    """Return the plain-text extract for a wikipedia_api ScrapeSource."""
    if source.source_kind != "wikipedia_api":
        raise ValueError(
            f"fetch_wikipedia_extract called on non-API source: {source.id}"
        )
    if not source.wikipedia_title:
        raise ValueError(
            f"Source {source.id} has source_kind=wikipedia_api but no wikipedia_title"
        )

    api_base = f"https://{source.language}.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "prop": "extracts",
        "titles": source.wikipedia_title,
        "format": "json",
        "explaintext": "true",
        "redirects": "1",
    }
    headers = {"User-Agent": USER_AGENT}

    _respect_rate_limit()
    try:
        response = httpx.get(
            api_base, params=params, headers=headers, timeout=_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise WikipediaApiError(
            f"Wikipedia API request failed for {source.id}: {exc}"
        ) from exc

    data = response.json()
    pages = data.get("query", {}).get("pages", {})
    if not pages:
        raise WikipediaApiError(f"No pages returned for {source.id}")

    page = next(iter(pages.values()))
    if "missing" in page:
        raise WikipediaApiError(
            f"Wikipedia article not found for {source.id} (title={source.wikipedia_title!r})"
        )

    extract = page.get("extract", "").strip()
    if not extract:
        raise WikipediaApiError(f"Empty extract returned for {source.id}")

    return extract
