"""
Graph assembly.

This is where the "graph" in LangGraph actually becomes a graph. Nodes are
plain async functions (state -> state); LangGraph handles the execution
order and state threading. The edges here are currently linear (plan ->
tools -> evidence -> reason -> report) because each stage's OUTPUT determines
the NEXT stage's INPUT necessarily (you can't rank evidence that doesn't
exist yet) -- the autonomy lives inside each node (what the planner decides,
which tools actually get called, how ranking scores evidence), not in
picking which node runs next.

If a future iteration adds a "request more evidence" loop (reasoner decides
confidence is too low and wants another research pass), THAT'S where a real
conditional edge belongs -- see `_should_deepen_research` below, wired in but
capped by settings.max_research_iterations to prevent infinite loops.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agents.evidence import evidence_node
from app.agents.planner import planner_node
from app.agents.reasoner import reasoner_node
from app.agents.report_generator import report_generator_node
from app.agents.state import ResearchState
from app.agents.tool_executor import tool_executor_node
from app.config import get_settings
from app.services.llm_client import LLMClient
from app.services.memory_service import MemoryService
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _should_deepen_research(state: ResearchState) -> str:
    """
    Conditional edge: if the reasoner's confidence is low AND we haven't
    exceeded the iteration cap, loop back to tool execution with the gaps
    the reasoner identified. Otherwise proceed to report generation.

    This is the one genuinely autonomous BRANCHING decision in the graph --
    the LLM's own confidence score determines control flow, not our code
    guessing whether more research is needed.
    """
    settings = get_settings()
    reasoning = state.get("reasoning")
    iterations = state.get("iterations", 0)

    if reasoning and reasoning.confidence_score < 0.5 and iterations < settings.max_research_iterations:
        logger.info(
            f"Low confidence ({reasoning.confidence_score}) -- looping back for more evidence "
            f"(iteration {iterations}/{settings.max_research_iterations})"
        )
        return "deepen"
    return "finalize"


def build_graph():
    llm = LLMClient()
    memory = MemoryService()
    graph = StateGraph(ResearchState)

    # Nodes that need the LLM are wrapped in real `async def` closures --
    # NOT lambdas. A lambda that calls an async function only returns an
    # unstarted coroutine object; it is not itself a coroutine function, so
    # LangGraph's inspect.iscoroutinefunction() check misses it and never
    # awaits the result, causing InvalidUpdateError ("Expected dict, got
    # <coroutine object>"). An `async def` wrapper IS correctly detected.
    async def _planner(state: ResearchState) -> ResearchState:
        return await planner_node(state, llm, memory)

    async def _reasoner(state: ResearchState) -> ResearchState:
        return await reasoner_node(state, llm)

    async def _report_generator(state: ResearchState) -> ResearchState:
        return await report_generator_node(state, llm)

    graph.add_node("planner", _planner)
    graph.add_node("tool_executor", tool_executor_node)
    graph.add_node("evidence", evidence_node)
    graph.add_node("reasoner", _reasoner)
    graph.add_node("report_generator", _report_generator)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "tool_executor")
    graph.add_edge("tool_executor", "evidence")
    graph.add_edge("evidence", "reasoner")

    graph.add_conditional_edges(
        "reasoner",
        _should_deepen_research,
        {
            "deepen": "tool_executor",   # loop back for another research pass
            "finalize": "report_generator",
        },
    )
    graph.add_edge("report_generator", END)

    return graph.compile()


async def run_research(query: str) -> ResearchState:
    app_graph = build_graph()
    initial_state: ResearchState = {
        "query": query,
        "current_stage": "started",
        "errors": [],
        "iterations": 0,
        "subquestion_offset": 0,
    }
    final_state = await app_graph.ainvoke(initial_state)
    return final_state
