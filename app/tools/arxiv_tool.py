from __future__ import annotations

import asyncio

from app.config import get_settings
from app.models.schemas import EvidenceItem, SourceTier, ToolName
from app.tools.base import ResearchTool


class ArxivTool(ResearchTool):
    name = "arxiv"

    def __init__(self):
        self._max_results = get_settings().max_arxiv_results

    async def run(self, query: str) -> list[EvidenceItem]:
        # arxiv's client is sync; offload to a thread so it doesn't block
        # the event loop while other tools run concurrently.
        return await asyncio.to_thread(self._search_sync, query)

    def _search_sync(self, query: str) -> list[EvidenceItem]:
        import arxiv

        search = arxiv.Search(
            query=query,
            max_results=self._max_results,
            sort_by=arxiv.SortCriterion.Relevance,
        )
        # arxiv>=4.0 removed Search.results() -- results are now fetched via
        # a Client, which centralizes pagination/rate-limit/retry behavior
        # that used to live awkwardly on Search itself.
        client = arxiv.Client()
        items: list[EvidenceItem] = []
        for result in client.results(search):
            items.append(
                EvidenceItem(
                    content=result.summary,
                    source_url=result.entry_id,
                    source_title=result.title,
                    tool_origin=ToolName.ARXIV,
                    source_tier=SourceTier.RESEARCH_PAPER,
                )
            )
        return items
