"""
Core data contracts for Inquira AI.

These schemas are the interfaces between layers (planner -> tools -> evidence ->
reasoner -> report). Keeping them centralized means every agent node validates
its input/output the same way, and the LLM's structured output is forced into
a predictable shape (no free-text parsing downstream).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #

class ToolName(str, Enum):
    TAVILY = "tavily"
    ARXIV = "arxiv"
    SCRAPER = "scraper"


class SourceTier(str, Enum):
    """Used to weight evidence during ranking. Lower = more authoritative."""
    OFFICIAL_DOCS = "official_docs"
    RESEARCH_PAPER = "research_paper"
    GOVERNMENT = "government"
    TECHNICAL_BLOG = "technical_blog"
    COMMUNITY = "community"
    UNKNOWN = "unknown"


class ResearchDepth(str, Enum):
    QUICK = "quick"        # 1-2 tools, few sources
    STANDARD = "standard"  # most tools, moderate sources
    DEEP = "deep"          # all tools, exhaustive


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #

class ResearchPlan(BaseModel):
    """
    Structured output of the Planner node. This is the LLM's autonomous
    decision about HOW to research the query -- nothing here is hardcoded
    by query keyword matching.
    """
    objective: str = Field(..., description="Restated, precise research objective")
    scope: str = Field(..., description="What is in / out of scope for this research")
    sub_questions: list[str] = Field(
        default_factory=list,
        description="Decomposed sub-questions the research must answer",
    )
    tools_to_use: list[ToolName] = Field(
        ..., description="Tools the planner has chosen to invoke, and why"
    )
    reasoning: str = Field(..., description="Why these tools/scope were chosen")
    depth: ResearchDepth = Field(default=ResearchDepth.STANDARD)


# --------------------------------------------------------------------------- #
# Evidence
# --------------------------------------------------------------------------- #

class EvidenceItem(BaseModel):
    """A single retrieved fact/passage with full source attribution."""
    content: str
    source_url: str
    source_title: Optional[str] = None
    tool_origin: ToolName
    source_tier: SourceTier = SourceTier.UNKNOWN
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)
    relevance_score: Optional[float] = None  # 0-1, set during ranking
    is_duplicate: bool = False


class RankedEvidence(BaseModel):
    items: list[EvidenceItem]
    total_collected: int
    total_after_dedup: int


# --------------------------------------------------------------------------- #
# Reasoning
# --------------------------------------------------------------------------- #

class ReasoningResult(BaseModel):
    agreements: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    synthesis: str = Field(..., description="Merged narrative from all evidence")
    confidence_score: float = Field(..., ge=0.0, le=1.0)


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #

class ReportSection(BaseModel):
    heading: str
    content: str


class ResearchReport(BaseModel):
    query: str
    executive_summary: str
    key_findings: list[str]
    detailed_analysis: list[ReportSection]
    comparisons: Optional[str] = None
    statistics: list[str] = Field(default_factory=list)
    references: list[str]  # formatted source URLs
    actionable_insights: list[str] = Field(default_factory=list)
    confidence_score: float
    generated_at: datetime = Field(default_factory=datetime.utcnow)


# --------------------------------------------------------------------------- #
# Memory
# --------------------------------------------------------------------------- #

class ResearchMemoryRecord(BaseModel):
    id: Optional[int] = None
    query: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    summary: str
    references: list[str]
    metadata: dict = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# API-facing
# --------------------------------------------------------------------------- #

class ResearchRequest(BaseModel):
    query: str = Field(..., min_length=3)
    depth_override: Optional[ResearchDepth] = None


class ResearchProgress(BaseModel):
    stage: str
    message: str
    percent: int = Field(ge=0, le=100)
