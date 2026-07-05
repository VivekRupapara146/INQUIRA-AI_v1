from __future__ import annotations

from app.config import get_settings
from app.models.schemas import EvidenceItem, SourceTier, ToolName
from app.tools.base import ResearchTool


class TavilyTool(ResearchTool):
    name = "tavily"

    def __init__(self):
        settings = get_settings()
        from tavily import AsyncTavilyClient

        self._client = AsyncTavilyClient(api_key=settings.tavily_api_key)
        self._max_results = settings.max_tavily_results

    async def run(self, query: str) -> list[EvidenceItem]:
        response = await self._client.search(
            query=query,
            search_depth="advanced",
            max_results=self._max_results,
            include_answer=False,
            # Without this, Tavily only returns a short AI-generated summary
            # snippet per result (a few hundred chars) -- fine for "what is
            # X" queries, but it silently drops details buried deeper in the
            # source (benchmarks, specific numbers, comparisons), which then
            # makes the reasoner correctly-but-uselessly report "not found in
            # evidence" for things that WERE on the page, just never fetched.
            include_raw_content="text",
        )

        items: list[EvidenceItem] = []
        for result in response.get("results", []):
            # Prefer the full page text when available; fall back to the
            # short snippet if raw extraction failed for that particular URL
            # (paywalls, JS-rendered pages, etc. can return raw_content=None).
            content = result.get("raw_content") or result.get("content", "")
            content = content[:4000]  # cap length -- reasoner truncates per-item anyway,
                                       # this just avoids sending Tavily-bloated pages we'll never use

            items.append(
                EvidenceItem(
                    content=content,
                    source_url=result.get("url", ""),
                    source_title=result.get("title"),
                    tool_origin=ToolName.TAVILY,
                    source_tier=self._classify_tier(result.get("url", "")),
                )
            )
        return items

    @staticmethod
    def _classify_tier(url: str) -> SourceTier:
        """
        Cheap heuristic pre-classification. The evidence ranker later refines
        this with LLM judgment, but a fast heuristic pass avoids spending a
        model call on obviously-tiered domains (e.g. .gov, docs.*, arxiv.org).
        """
        url_lower = url.lower()
        if any(d in url_lower for d in ["docs.", "documentation", "readme"]):
            return SourceTier.OFFICIAL_DOCS
        if "arxiv.org" in url_lower:
            return SourceTier.RESEARCH_PAPER
        if url_lower.endswith(".gov") or ".gov/" in url_lower:
            return SourceTier.GOVERNMENT
        if any(d in url_lower for d in ["medium.com", "dev.to", "blog"]):
            return SourceTier.TECHNICAL_BLOG
        if any(d in url_lower for d in ["reddit.com", "stackoverflow.com", "forum"]):
            return SourceTier.COMMUNITY
        return SourceTier.UNKNOWN
