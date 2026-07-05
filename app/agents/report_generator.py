from __future__ import annotations

from app.agents.prompts import REPORT_PROMPT
from app.agents.state import ResearchState
from app.models.schemas import ReportSection, ResearchReport
from app.services.llm_client import LLMClient
from app.utils.logger import get_logger
from pydantic import BaseModel, Field

logger = get_logger(__name__)


class _ReportDraft(BaseModel):
    """Intermediate structured output -- report_generator fills in the parts
    the LLM shouldn't own (references list, confidence_score, query, timestamp)
    after this comes back, to guarantee those fields are never hallucinated."""
    executive_summary: str
    key_findings: list[str]
    detailed_analysis: list[ReportSection]
    comparisons: str | None = None
    statistics: list[str] = Field(default_factory=list)
    actionable_insights: list[str] = Field(default_factory=list)


async def report_generator_node(state: ResearchState, llm: LLMClient) -> ResearchState:
    query = state["query"]
    reasoning = state["reasoning"]
    evidence = state.get("ranked_evidence", [])

    # References are taken directly from evidence URLs -- never from the LLM
    # -- so a citation can never be hallucinated (a pitfall the brief calls
    # out explicitly).
    references = sorted({item.source_url for item in evidence if item.source_url})

    prompt = REPORT_PROMPT.format(
        query=query,
        synthesis=reasoning.synthesis,
        agreements=reasoning.agreements,
        contradictions=reasoning.contradictions,
        uncertainty_notes=reasoning.uncertainty_notes,
        confidence_score=reasoning.confidence_score,
        references=references,
    )

    draft: _ReportDraft = await llm.generate_structured(prompt, _ReportDraft)

    report = ResearchReport(
        query=query,
        executive_summary=draft.executive_summary,
        key_findings=draft.key_findings,
        detailed_analysis=draft.detailed_analysis,
        comparisons=draft.comparisons,
        statistics=draft.statistics,
        references=references,
        actionable_insights=draft.actionable_insights,
        confidence_score=reasoning.confidence_score,
    )

    logger.info(f"Report generated for query={query!r} with {len(references)} references")

    return {
        **state,
        "report": report,
        "current_stage": "report_complete",
    }
