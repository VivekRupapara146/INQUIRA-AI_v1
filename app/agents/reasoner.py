from __future__ import annotations

from app.agents.prompts import REASONING_PROMPT
from app.agents.state import ResearchState
from app.models.schemas import EvidenceItem, ReasoningResult
from app.services.llm_client import LLMClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

MAX_EVIDENCE_FOR_REASONING = 20  # keep prompt size sane; ranking already sorted best-first
MAX_CHARS_PER_ITEM = 2500  # raised from 600 now that tools fetch full page text, not
                            # just short snippets -- 20 items * 2500 chars stays well
                            # within context limits while actually surfacing buried details


def _format_evidence_block(items: list[EvidenceItem]) -> str:
    lines = []
    for i, item in enumerate(items[:MAX_EVIDENCE_FOR_REASONING], start=1):
        lines.append(
            f"[{i}] (tier={item.source_tier.value}, source={item.source_url})\n"
            f"    {item.content[:MAX_CHARS_PER_ITEM]}"
        )
    return "\n\n".join(lines)


async def reasoner_node(state: ResearchState, llm: LLMClient) -> ResearchState:
    plan = state["plan"]
    evidence = state.get("ranked_evidence", [])

    if not evidence:
        logger.warning("No evidence available for reasoning -- producing low-confidence result")
        result = ReasoningResult(
            synthesis="Insufficient evidence was retrieved to answer this query reliably.",
            confidence_score=0.1,
            uncertainty_notes=["No evidence passed collection/dedup for this query."],
        )
        return {**state, "reasoning": result, "current_stage": "reasoning_complete"}

    prompt = REASONING_PROMPT.format(
        objective=plan.objective,
        sub_questions="\n".join(f"- {q}" for q in plan.sub_questions),
        evidence_block=_format_evidence_block(evidence),
    )

    reasoning: ReasoningResult = await llm.generate_structured(prompt, ReasoningResult)
    logger.info(f"Reasoning complete -- confidence={reasoning.confidence_score}")

    return {
        **state,
        "reasoning": reasoning,
        "current_stage": "reasoning_complete",
        # increment here (not in the conditional edge function) because
        # LangGraph conditional-edge functions only select the next node --
        # they cannot mutate state. This is the one place that "knows" a
        # reasoning pass just completed.
        "iterations": state.get("iterations", 0) + 1,
    }
