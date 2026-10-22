from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup, Tag

from app.scraper.sources_config import ScrapeSource

logger = logging.getLogger(__name__)

MIN_USEFUL_TEXT_LENGTH = 200


class ExtractionError(Exception):
    """Raised when no usable text could be extracted from a page."""


def extract_text(html: str, source: ScrapeSource) -> str:
    """Extract cleaned, human-readable text from a page's HTML.

    Strategy:
    1. Parse with BeautifulSoup, strip known noise elements (nav/footer/ads/...).
    2. Try the source's configured content_selector.
    3. If that yields too little text, fall back to the largest <article>/<main>
       block, then finally the whole <body> (still noise-stripped).
    """
    soup = BeautifulSoup(html, "html.parser")

    for selector in source.exclude_selectors:
        for element in soup.select(selector):
            element.decompose()

    candidate = _try_selector(soup, source.content_selector)
    if candidate is None or _text_length(candidate) < MIN_USEFUL_TEXT_LENGTH:
        candidate = _fallback_candidate(soup) or candidate

    if candidate is None:
        raise ExtractionError(f"No content found for source={source.id} url={source.url}")

    text = _clean_text(candidate.get_text(separator="\n"))
    if len(text) < MIN_USEFUL_TEXT_LENGTH:
        raise ExtractionError(
            f"Extracted text too short ({len(text)} chars) for source={source.id} "
            f"url={source.url} — page structure may have changed, check content_selector."
        )
    return text


def _try_selector(soup: BeautifulSoup, selector: str | None) -> Tag | None:
    if not selector:
        return None
    for candidate_selector in selector.split(","):
        match = soup.select_one(candidate_selector.strip())
        if match is not None:
            return match
    return None


def _fallback_candidate(soup: BeautifulSoup) -> Tag | None:
    for tag_name in ("article", "main"):
        match = soup.find(tag_name)
        if match is not None and _text_length(match) >= MIN_USEFUL_TEXT_LENGTH:
            return match
    return soup.body


def _text_length(tag: Tag) -> int:
    return len(tag.get_text(strip=True))


def _clean_text(raw_text: str) -> str:
    lines = [line.strip() for line in raw_text.splitlines()]
    lines = [line for line in lines if line]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()
