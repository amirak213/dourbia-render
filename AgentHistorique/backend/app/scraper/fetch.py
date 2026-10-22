from __future__ import annotations

import logging
import time
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "DourbiaHistoricalBot/1.0 (+https://dourbia.tn; contact: [email protected])"
DEFAULT_DELAY_SECONDS = 2.0
DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_RETRIES = 2


class FetchError(Exception):
    """Raised when a page cannot be fetched or is disallowed by robots.txt."""


@dataclass
class FetchResult:
    url: str
    status_code: int
    html: str
    fetched_at_epoch: float


class RespectfulFetcher:
    """Fetches pages one at a time, checking robots.txt and pacing requests.

    Intentionally sequential and slow (DEFAULT_DELAY_SECONDS between any two
    requests, even across different hosts) — this is a one-off batch job over
    ~8 sources, not a crawler. No concurrency by design.
    """

    def __init__(
        self,
        *,
        user_agent: str = USER_AGENT,
        delay_seconds: float = DEFAULT_DELAY_SECONDS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._user_agent = user_agent
        self._delay_seconds = delay_seconds
        self._timeout_seconds = timeout_seconds
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._last_request_at: float | None = None

    def fetch(self, url: str) -> FetchResult:
        if not self._is_allowed_by_robots(url):
            raise FetchError(f"Blocked by robots.txt: {url}")

        self._respect_delay()

        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                with httpx.Client(
                    timeout=self._timeout_seconds,
                    follow_redirects=True,
                    headers={
                        "User-Agent": self._user_agent,
                        "Accept": (
                            "text/html,application/xhtml+xml,application/xml;"
                            "q=0.9,image/webp,*/*;q=0.8"
                        ),
                        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
                    },
                ) as client:
                    response = client.get(url)
                self._last_request_at = time.monotonic()

                if response.status_code == 429:
                    logger.warning("429 rate-limited on %s, backing off", url)
                    time.sleep(self._delay_seconds * 3)
                    continue

                response.raise_for_status()
                return FetchResult(
                    url=url,
                    status_code=response.status_code,
                    html=response.text,
                    fetched_at_epoch=time.time(),
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning(
                    "Fetch attempt %s/%s failed for %s: %s", attempt, MAX_RETRIES, url, exc
                )
                if attempt < MAX_RETRIES:
                    time.sleep(self._delay_seconds)

        raise FetchError(f"Failed to fetch {url} after {MAX_RETRIES} attempts") from last_exc

    def _respect_delay(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self._delay_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _is_allowed_by_robots(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        parser = self._robots_cache.get(origin)
        if parser is None:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(f"{origin}/robots.txt")
            try:
                parser.read()
            except Exception:
                # If robots.txt is unreachable, err on the side of allowing —
                # but log it so a human can double-check manually before the
                # source is trusted long-term.
                logger.warning(
                    "Could not read robots.txt for %s — proceeding cautiously", origin
                )
                self._robots_cache[origin] = parser
                return True
            self._robots_cache[origin] = parser

        return parser.can_fetch(self._user_agent, url)
