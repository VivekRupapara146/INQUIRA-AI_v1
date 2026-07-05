"""
Planner node.

This is the node the assessment cares about most: it's where "autonomous
decision making" either genuinely happens or gets faked. The LLM receives
ONLY the raw query and a description of available tools -- it must decide
scope, sub-questions, and tool selection itself. There is no
`if "paper" in query: use arxiv` anywhere in this codebase.
"""

from __future__ import annotations

from app.agents.prompts import PAST_CONTEXT_TEMPLATE, PLANNER_PROMPT
from app.agents.state import ResearchState
from app.models.schemas import ResearchPlan
from app.services.llm_client import LLMClient
from app.services.memory_service import MemoryService
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def _build_past_context_block(query: str, memory: MemoryService) -> str:
    """
    Looks up prior research related to this query and formats it as optional
    context for the planner. Returns an empty string if nothing relevant was
    found -- the prompt template handles that cleanly (no dangling section).

    Uses find_similar()'s lexical matching, which is coarse by design (see
    memory_service.py) -- that's why the prompt explicitly tells the planner
    to judge relevance itself rather than trust this blindly.
    """
    try:
        similar = await memory.find_similar(query, limit=3)
    except Exception as exc:  # noqa: BLE001 -- memory lookup failing should never block planning
        logger.warning(f"Memory lookup failed, proceeding without past context: {exc}")
        return ""

    if not similar:
        return ""

    entries = "\n".join(
        f'- "{record.query}" (researched {record.timestamp.strftime("%Y-%m-%d")}): {record.summary}'
        for record in similar
    )
    return PAST_CONTEXT_TEMPLATE.format(entries=entries)


async def planner_node(state: ResearchState, llm: LLMClient, memory: MemoryService) -> ResearchState:
    query = state["query"]
    logger.info(f"Planning research for query: {query!r}")

    past_context_block = await _build_past_context_block(query, memory)
    if past_context_block:
        logger.info("Found relevant past research -- injecting as planner context")

    prompt = PLANNER_PROMPT.format(query=query, past_context_block=past_context_block)
    plan: ResearchPlan = await llm.generate_structured(prompt, ResearchPlan)

    logger.info(
        f"Plan produced -- tools={ [t.value for t in plan.tools_to_use] }, "
        f"depth={plan.depth.value}, sub_questions={len(plan.sub_questions)}"
    )

    return {
        **state,
        "plan": plan,
        "current_stage": "planning_complete",
    }
