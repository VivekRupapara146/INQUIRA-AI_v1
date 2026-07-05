"""
Evidence node: dedup + rank.

Two responsibilities, kept in one node because they operate on the same
list in sequence (dedup must happen before ranking, or duplicates would
skew the final evidence set).

Dedup uses text-similarity (difflib) rather than an embeddings model -- for
an MVP with <=30-40 evidence items this is fast, has zero extra API cost, and
is easy to explain/defend in an interview ("why difflib not embeddings?" ->
scale doesn't justify the extra dependency/cost here; would swap to embedding
cosine-similarity if evidence volume grew into the hundreds).
"""

from __future__ import annotations

from difflib import SequenceMatcher

from app.agents.state import ResearchState
from app.models.schemas import EvidenceItem, SourceTier
from app.utils.logger import get_logger

logger = get_logger(__name__)

DUPLICATE_SIMILARITY_THRESHOLD = 0.85

# Conservative floor -- even the worst source tier (UNKNOWN, weight=0.3)
# contributes 0.6*0.3=0.18 on its own, so 0.3 only filters items that are
# BOTH low-tier AND have near-zero lexical overlap with the sub-questions.
# Set deliberately low: on small evidence sets (5-15 items, typical for this
# app) an aggressive threshold risks starving the reasoner entirely, which
# is a worse outcome than letting a mediocre source through.
MIN_RELEVANCE_SCORE = 0.3

# Lower number = more authoritative. Drives the ranking score.
TIER_WEIGHTS: dict[SourceTier, float] = {
    SourceTier.OFFICIAL_DOCS: 1.0,
    SourceTier.RESEARCH_PAPER: 0.9,
    SourceTier.GOVERNMENT: 0.85,
    SourceTier.TECHNICAL_BLOG: 0.6,
    SourceTier.COMMUNITY: 0.4,
    SourceTier.UNKNOWN: 0.3,
}


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a[:500], b[:500]).ratio()


def _deduplicate(items: list[EvidenceItem]) -> list[EvidenceItem]:
    kept: list[EvidenceItem] = []
    for item in items:
        if not item.content.strip():
            continue
        is_dup = any(_similarity(item.content, k.content) >= DUPLICATE_SIMILARITY_THRESHOLD for k in kept)
        if is_dup:
            continue
        kept.append(item)
    return kept


def _relevance_score(item: EvidenceItem, sub_questions: list[str]) -> float:
    """
    Cheap lexical-overlap relevance proxy: fraction of sub-question terms
    that appear in the evidence content. Combined with tier weight for the
    final ranking score.
    """
    if not sub_questions:
        return 0.5

    content_lower = item.content.lower()
    scores = []
    for q in sub_questions:
        terms = [t for t in q.lower().split() if len(t) > 3]
        if not terms:
            continue
        hits = sum(1 for t in terms if t in content_lower)
        scores.append(hits / len(terms))
    return max(scores) if scores else 0.3


def _rank(items: list[EvidenceItem], sub_questions: list[str]) -> list[EvidenceItem]:
    for item in items:
        tier_weight = TIER_WEIGHTS.get(item.source_tier, 0.3)
        relevance = _relevance_score(item, sub_questions)
        # weighted blend: tier matters more than raw lexical overlap
        item.relevance_score = round(0.6 * tier_weight + 0.4 * relevance, 3)
    return sorted(items, key=lambda i: i.relevance_score or 0, reverse=True)


def _filter_irrelevant(items: list[EvidenceItem]) -> list[EvidenceItem]:
    """
    Drops items below MIN_RELEVANCE_SCORE -- ranking alone only reorders,
    it never removes anything, so without this step "irrelevant" content
    would just sort to the bottom and still reach the reasoner.

    Safety fallback: if filtering would remove EVERYTHING (e.g. a genuinely
    obscure query where nothing scored well), keep the original ranked list
    instead. A reasoner with mediocre evidence produces a low-confidence
    report; a reasoner with ZERO evidence produces a useless one -- the
    former is always the better failure mode.
    """
    filtered = [item for item in items if (item.relevance_score or 0) >= MIN_RELEVANCE_SCORE]
    if not filtered and items:
        logger.warning(
            f"Relevance filter would have removed all {len(items)} evidence items -- "
            f"keeping unfiltered ranked list instead (better a weak report than an empty one)"
        )
        return items
    return filtered


async def evidence_node(state: ResearchState) -> ResearchState:
    raw = state.get("raw_evidence", [])
    plan = state["plan"]

    deduped = _deduplicate(raw)
    ranked = _rank(deduped, plan.sub_questions if plan else [])
    filtered = _filter_irrelevant(ranked)

    logger.info(
        f"Evidence: {len(raw)} raw -> {len(deduped)} after dedup -> "
        f"{len(filtered)} after relevance filter (threshold={MIN_RELEVANCE_SCORE})"
    )

    return {
        **state,
        "ranked_evidence": filtered,
        "current_stage": "evidence_ranked",
    }
