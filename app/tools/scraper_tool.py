from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings
from app.models.schemas import EvidenceItem, SourceTier, ToolName
from app.tools.base import ResearchTool


class ScraperTool(ResearchTool):
    """
    Fetches and extracts readable text from a specific URL.

    Unlike Tavily/ArXiv (which discover sources), the scraper is used when the
    planner already knows a specific documentation/reference URL is relevant
    (e.g. "official LangGraph docs") and wants full-page content rather than a
    search snippet.
    """

    name = "scraper"

    def __init__(self):
        self._timeout = get_settings().request_timeout_seconds

    async def run(self, query: str) -> list[EvidenceItem]:
        # `query` here is expected to be a URL when this tool is selected by
        # the planner; the planner is responsible for passing a real URL.
        if not query.startswith("http"):
            return []

        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            resp = await client.get(query, headers={"User-Agent": "InquiraAI-Research/1.0"})
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        text = " ".join(soup.get_text(separator=" ").split())[:5000]
        title = soup.title.string if soup.title else query

        return [
            EvidenceItem(
                content=text,
                source_url=query,
                source_title=title,
                tool_origin=ToolName.SCRAPER,
                source_tier=SourceTier.OFFICIAL_DOCS,
            )
        ]
