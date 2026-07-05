"""
Centralized prompt templates.

Why: the brief explicitly flags "Prompt Spaghetti" as a pitfall. Keeping
templates here (instead of inline f-strings in each node) means prompts are
reviewable, versionable, and reusable across nodes.
"""

PLANNER_PROMPT = """You are the planning module of an autonomous research agent.

Given a user's research query, decide HOW to research it. Do not answer the
query yourself -- only plan the research strategy.

Available tools:
- tavily: general web search, good for current information, comparisons, news
- arxiv: academic paper search, good for technical/scientific depth
- scraper: fetches full content from a SPECIFIC known URL (only useful if you
  know an exact documentation URL worth reading in full)

User query: {query}
{past_context_block}
Decide:
1. The precise research objective (what would fully answer this query?)
2. Scope boundaries (what's out of scope, to keep the research focused)
3. 2-5 sub-questions that decompose the query
4. Which tools to use and why (choose based on the query's nature, not keywords)
5. Research depth: "quick" for simple factual queries, "standard" for most
   queries, "deep" for broad/comparative/multi-part queries

If past research context was provided above, use it only if genuinely
relevant to the current query -- it may be unrelated (a coarse lexical match,
not a guaranteed semantic one). Do not let it narrow your scope or sub-
questions if it doesn't actually overlap with what's being asked now.
"""

PAST_CONTEXT_TEMPLATE = """
Relevant past research found in memory (may or may not be useful -- judge
for yourself whether it actually applies to the current query):
{entries}
"""

EVIDENCE_TIER_PROMPT = """Classify the reliability tier of this source for a
research report. Consider domain authority, content type, and whether it's
official/primary vs secondary/community content.

Source URL: {url}
Source title: {title}
Content excerpt: {excerpt}

Return one tier: official_docs, research_paper, government, technical_blog,
community, or unknown.
"""

REASONING_PROMPT = """You are the reasoning module of an autonomous research
agent. You have collected evidence from multiple sources. Your job is to
REASON over it, not just summarize it.

Research objective: {objective}
Sub-questions to answer: {sub_questions}

Evidence collected (each tagged with source and reliability tier):
{evidence_block}

Analyze this evidence and identify:
1. Points of AGREEMENT across sources (these increase confidence)
2. Any CONTRADICTIONS between sources (name which sources disagree, and why
   that might be -- e.g. outdated info, different scope, differing methodology)
3. UNCERTAINTY -- where evidence is thin, ambiguous, or missing relative to
   the sub-questions
4. A synthesized narrative that MERGES complementary findings into a coherent
   explanation (not a concatenation of source summaries)
5. An overall confidence score (0.0-1.0) based on: source tier quality,
   agreement level, and evidence coverage of the sub-questions
"""

REPORT_PROMPT = """Generate a structured, professional research report from
the reasoning below. Write for a technical reader who wants a decision-useful
report, not marketing copy.

Query: {query}
Reasoning synthesis: {synthesis}
Agreements: {agreements}
Contradictions: {contradictions}
Uncertainty notes: {uncertainty_notes}
Confidence score: {confidence_score}
Available references: {references}

Produce:
- executive_summary (2-4 sentences)
- key_findings (bullet list, 3-6 items)
- detailed_analysis (2-4 sections with heading + content)
- comparisons (if the query was comparative, else null)
- statistics (any concrete numbers found in evidence, else empty list)
- actionable_insights (practical takeaways, 2-4 items)

Never invent a statistic or citation that isn't grounded in the evidence
provided above.
"""
