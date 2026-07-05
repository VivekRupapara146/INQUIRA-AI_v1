"""
Common interface for all research tools.

Why: the planner selects tools by ToolName and calls `.run(query)` on
whichever ones it picked -- it never needs to know Tavily's SDK differs from
ArXiv's differs from the scraper's. New tools just implement this ABC and
register themselves in the TOOL_REGISTRY (see tools/__init__ wiring in graph.py).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.schemas import EvidenceItem


class ResearchTool(ABC):
    name: str

    @abstractmethod
    async def run(self, query: str) -> list[EvidenceItem]:
        """Execute the tool and return normalized EvidenceItem objects."""
        raise NotImplementedError

    async def safe_run(self, query: str) -> list[EvidenceItem]:
        """
        Wrapper that guarantees a tool failure (timeout, API error, empty
        results) never crashes the whole research pipeline -- it just
        contributes zero evidence. Required per the brief's "Hidden Errors"
        pitfall: failures must degrade gracefully, not blow up the graph.
        """
        try:
            return await self.run(query)
        except Exception as exc:  # noqa: BLE001 - intentional broad catch at boundary
            from app.utils.logger import get_logger

            get_logger(self.__class__.__name__).warning(
                f"Tool '{self.name}' failed for query={query!r}: {exc}"
            )
            return []
