from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"

REGION_TO_TAVILY_COUNTRY: dict[str, str] = {
    "fr-fr": "france",
    "fr": "france",
    "en-us": "united states",
    "en-gb": "united kingdom",
}


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str
    source: str = "duckduckgo"


class BaseWebSearchTool:
    def search(
        self,
        query: str,
        max_results: int = 3,
        *,
        region: str | None = None,
    ) -> list[WebSearchResult]:
        raise NotImplementedError


class DuckDuckGoSearchTool(BaseWebSearchTool):
    def __init__(self, *, region: str = "fr-fr") -> None:
        self._region = region

    def search(
        self,
        query: str,
        max_results: int = 3,
        *,
        region: str | None = None,
    ) -> list[WebSearchResult]:
        cleaned_query = query.strip()
        if not cleaned_query:
            return []

        search_region = region or self._region

        try:
            from duckduckgo_search import DDGS

            raw_results: list[dict[str, object]] = []
            with DDGS() as ddgs:
                for backend in ("html", "auto"):
                    try:
                        raw_results = list(
                            ddgs.text(
                                cleaned_query,
                                max_results=max_results,
                                region=search_region,
                                backend=backend,
                            )
                        )
                    except TypeError:
                        raw_results = list(
                            ddgs.text(
                                cleaned_query,
                                max_results=max_results,
                                region=search_region,
                            )
                        )
                    if raw_results:
                        break
        except Exception:
            logger.exception(
                "DuckDuckGo web search failed for query=%r region=%s",
                cleaned_query,
                search_region,
            )
            return []

        return _map_generic_results(raw_results, source="duckduckgo")


class TavilySearchTool(BaseWebSearchTool):
    def __init__(
        self,
        *,
        api_key: str,
        region: str = "fr-fr",
        search_depth: str = "basic",
        timeout_seconds: float = 15.0,
    ) -> None:
        self._api_key = api_key.strip()
        self._region = region
        self._search_depth = search_depth
        self._timeout_seconds = timeout_seconds

    def search(
        self,
        query: str,
        max_results: int = 3,
        *,
        region: str | None = None,
    ) -> list[WebSearchResult]:
        cleaned_query = query.strip()
        if not cleaned_query:
            return []
        if not self._api_key:
            logger.warning("Tavily API key is missing; skipping web search.")
            return []

        payload: dict[str, object] = {
            "api_key": self._api_key,
            "query": cleaned_query,
            "max_results": max(1, max_results),
            "search_depth": self._search_depth,
            "include_answer": False,
            "include_raw_content": False,
        }
        country = _region_to_tavily_country(region or self._region)
        if country:
            payload["country"] = country

        try:
            response = httpx.post(
                TAVILY_SEARCH_URL,
                json=payload,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            logger.exception(
                "Tavily web search HTTP error for query=%r status=%s",
                cleaned_query,
                exc.response.status_code,
            )
            return []
        except Exception:
            logger.exception("Tavily web search failed for query=%r", cleaned_query)
            return []

        raw_results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(raw_results, list):
            return []

        results: list[WebSearchResult] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            snippet = str(item.get("content") or item.get("snippet") or "").strip()
            if not title and not url and not snippet:
                continue
            results.append(
                WebSearchResult(
                    title=title or url or "Résultat web",
                    url=url,
                    snippet=snippet,
                    source="tavily",
                )
            )
        return results


def _region_to_tavily_country(region: str | None) -> str | None:
    if not region:
        return None
    normalized = region.strip().lower().replace("_", "-")
    return REGION_TO_TAVILY_COUNTRY.get(normalized)


def _map_generic_results(
    raw_results: list[dict[str, object]],
    *,
    source: str,
) -> list[WebSearchResult]:
    results: list[WebSearchResult] = []
    for item in raw_results or []:
        title = str(item.get("title") or "").strip()
        url = str(item.get("href") or item.get("url") or "").strip()
        snippet = str(item.get("body") or item.get("snippet") or "").strip()
        if not title and not url and not snippet:
            continue
        results.append(
            WebSearchResult(
                title=title or url or "Résultat web",
                url=url,
                snippet=snippet,
                source=source,
            )
        )
    return results


def create_web_search_tool(settings: Settings) -> BaseWebSearchTool:
    provider = settings.web_search_provider.strip().lower()
    if provider == "tavily":
        if not settings.tavily_api_key.strip():
            logger.warning(
                "WEB_SEARCH_PROVIDER=tavily but TAVILY_API_KEY is empty; "
                "falling back to DuckDuckGo."
            )
            return DuckDuckGoSearchTool(region=settings.web_search_region)
        return TavilySearchTool(
            api_key=settings.tavily_api_key,
            region=settings.web_search_region,
            search_depth=settings.tavily_search_depth,
            timeout_seconds=settings.web_search_timeout_seconds,
        )
    if provider != "duckduckgo":
        logger.warning(
            "Unknown WEB_SEARCH_PROVIDER=%r; falling back to DuckDuckGo.",
            settings.web_search_provider,
        )
    return DuckDuckGoSearchTool(region=settings.web_search_region)
