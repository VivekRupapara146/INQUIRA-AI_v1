"""
Tool execution node.

Runs every tool the planner selected CONCURRENTLY via asyncio.gather -- this
is the "Parallel Research" requirement from the brief. Each tool is wrapped
in `safe_run` so one failing tool (timeout, rate limit, empty results) never
kills the others.

Fans out across BOTH axes:
  - tools (Tavily / ArXiv / Scraper run concurrently -- unchanged from before)
  - sub-questions (NEW: previously only sub_questions[0] was ever searched,
    silently discarding everything else the planner decomposed; e.g. a
    3-way framework comparison would only ever search "framework A vs B vs C"
    once, never anything targeting the specific gaps in that first query)

The sub-question BATCH is capped (settings.max_subquestions_per_batch) and
offset-tracked in state. This serves two purposes at once:
  1. First pass covers up to `cap` sub-questions instead of just 1.
  2. If the confidence-loop fires (see graph.py), the retry naturally uses
     the NEXT batch of sub-questions (offset advances), not a repeat of the
     same search -- fixing the observed failure mode where retrying the
     identical query sometimes made confidence WORSE, not better.
"""

from __future__ import annotations

import asyncio

from app.agents.state import ResearchState
from app.config import get_settings
from app.models.schemas import ToolName
from app.tools.arxiv_tool import ArxivTool
from app.tools.scraper_tool import ScraperTool
from app.tools.tavily_tool import TavilyTool
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Central registry -- adding a new tool means: implement ResearchTool,
# register it here. No other file needs to change.
TOOL_REGISTRY = {
    ToolName.TAVILY: TavilyTool,
    ToolName.ARXIV: ArxivTool,
    ToolName.SCRAPER: ScraperTool,
}


async def tool_executor_node(state: ResearchState) -> ResearchState:
    plan = state["plan"]
    if plan is None:
        raise ValueError("tool_executor_node requires a plan in state")

    settings = get_settings()
    cap = settings.max_subquestions_per_batch
    offset = state.get("subquestion_offset", 0)

    # Select this pass's batch of sub-questions. If the plan produced none,
    # or we've exhausted them (offset ran past the end), fall back to the
    # raw query rather than running zero searches.
    batch = plan.sub_questions[offset : offset + cap] if plan.sub_questions else []
    if not batch:
        batch = [state["query"]]

    logger.info(
        f"Executing tools in parallel: {[t.value for t in plan.tools_to_use]} "
        f"x {len(batch)} sub-question(s) (offset={offset}): {batch}"
    )

    tasks = []
    for tool_name in plan.tools_to_use:
        tool_cls = TOOL_REGISTRY.get(tool_name)
        if tool_cls is None:
            logger.warning(f"Unknown tool selected by planner: {tool_name}")
            continue
        tool_instance = tool_cls()
        for sub_query in batch:
            tasks.append(tool_instance.safe_run(sub_query))

    results_per_call = await asyncio.gather(*tasks) if tasks else []

    new_evidence = [item for call_results in results_per_call for item in call_results]
    # Accumulate across passes (important for the confidence-loop case --
    # a retry should ADD evidence from new sub-questions, not replace what
    # the first pass already found).
    combined_evidence = state.get("raw_evidence", []) + new_evidence

    logger.info(
        f"Collected {len(new_evidence)} new evidence items this pass "
        f"({len(combined_evidence)} total across all passes)"
    )

    return {
        **state,
        "raw_evidence": combined_evidence,
        "subquestion_offset": offset + len(batch),
        "current_stage": "evidence_collected",
    }
