"""
Shared state that flows through every node in the LangGraph.

Each node reads what it needs and writes back its contribution -- this is
what lets nodes stay decoupled (a node never reaches into another node's
internals, it only reads/writes the shared state dict).
"""

from __future__ import annotations

from typing import Optional, TypedDict

from app.models.schemas import (
    EvidenceItem,
    ReasoningResult,
    ResearchPlan,
    ResearchReport,
)


class ResearchState(TypedDict, total=False):
    # input
    query: str

    # populated by planner node
    plan: Optional[ResearchPlan]

    # populated by tool-execution node (parallel fan-out)
    raw_evidence: list[EvidenceItem]

    # populated by evidence node (dedup + rank)
    ranked_evidence: list[EvidenceItem]

    # populated by reasoner node
    reasoning: Optional[ReasoningResult]

    # populated by report node
    report: Optional[ResearchReport]

    # progress tracking for UI streaming
    current_stage: str
    errors: list[str]

    # how many times the reasoner->tool_executor loop has fired (see graph.py
    # _should_deepen_research) -- prevents infinite research loops
    iterations: int

    # index into plan.sub_questions marking where the NEXT tool_executor batch
    # should start. Advances after every tool_executor pass, so a confidence-
    # loop retry searches sub-questions the first pass didn't get to, instead
    # of blindly re-running the same search (see agents/tool_executor.py)
    subquestion_offset: int
