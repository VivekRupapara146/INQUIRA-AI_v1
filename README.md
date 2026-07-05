# Inquira AI

**Autonomous Research. Verified Insights.**

An autonomous multi-agent research system: give it a query, and it independently plans a research strategy, selects and runs tools in parallel across multiple sub-questions, deduplicates and filters evidence, ranks it by source reliability, reasons over it (agreements, contradictions, confidence), and produces a structured, cited report — exportable to Markdown or PDF, with every past query searchable in history.

This is not a chatbot or a plain RAG pipeline. A chatbot answers from a prompt. This system *researches*: it decides what to look for, where to look, whether it found enough, and only then answers.

---

## Requirements checklist

Built against an autonomous-research-agent assessment brief. Every core and bonus requirement is implemented and verified against real APIs, not just described:

| Requirement | Status | Where |
|---|---|---|
| Accept a user query/topic | ✅ | `ResearchRequest`, frontend input |
| Search external sources | ✅ | Tavily (web) + ArXiv (papers) + Scraper (specific URLs), planner-selected |
| Extract relevant information | ✅ | Full page text via Tavily's raw content, not just short snippets |
| Remove duplicate content | ✅ | Text-similarity dedup (`evidence.py`) |
| Remove irrelevant content | ✅ | Relevance-floor filtering with a safety fallback against over-filtering |
| Key points / findings / references / actionable insights | ✅ | `ResearchReport` schema — references pulled directly from evidence, never LLM-invented |
| **Bonus:** LLM autonomously selects sources | ✅ | Planner receives only tool *descriptions*, decides selection itself — no keyword matching |
| **Bonus:** Parallel information gathering | ✅ | Concurrent across tools **and** sub-questions (`asyncio.gather`) |
| **Bonus:** Export as PDF/Markdown | ✅ | In-memory generation, streamed directly to the browser |
| **Bonus:** Memory of past searches | ✅ | SQLite-backed; also **actively reused** — the planner checks for relevant past research before planning |

---

## Architecture

```
User Query
    │
    ▼
┌──────────────────────┐
│ Planner               │  LLM decides: objective, scope, sub-questions,
│ (+ past-memory context)│  WHICH tools to use. Checks SQLite for related
└──────────┬────────────┘  prior research and offers it as optional context.
           │
           ▼
┌────────────────────────┐
│ Tool Executor            │  Runs every selected tool CONCURRENTLY, across a
│ Tavily │ ArXiv │ Scraper  │  BATCH of sub-questions (not just the first one).
└──────────┬───────────────┘  Batch offset advances each pass -- see below.
           ▼
┌───────────┐
│ Evidence  │  Dedup (text similarity) → Rank (source tier + relevance)
│           │  → Filter (drop items below a relevance floor)
└─────┬─────┘
      ▼
┌──────────┐
│ Reasoner │  LLM: agreements / contradictions / uncertainty / confidence
└────┬─────┘
     │
     ├── confidence < 0.5 and iterations < cap ──► loop back to Tool Executor,
     │                                             which searches the NEXT batch
     │                                             of sub-questions (not a repeat)
     ▼
┌──────────────────┐
│ Report Generator  │  Structured report; references pulled from evidence,
└─────────┬─────────┘  never hallucinated
          ▼
   Saved to SQLite (full report) ──► visible in sidebar history,
                                      reopenable without re-running research
```

Built with **LangGraph** as a `StateGraph`, not a linear chain — the core requirement this satisfies is genuine autonomy: the planner's tool selection and the reasoner's confidence score are LLM decisions that actually change control flow, not decoration on top of a fixed pipeline.

### Sub-question batching (the fix that mattered most)

Early versions of this project only ever searched `sub_questions[0]`, silently discarding the rest of what the planner decomposed — a "compare 3 frameworks" query would only ever search framework #1, leaving the report with real, admitted gaps for the others. The fix: `tool_executor_node` tracks a `subquestion_offset` in graph state and searches a *batch* of sub-questions each pass (capped by `MAX_SUBQUESTIONS_PER_BATCH`, default 3). When the confidence-loop fires, the retry naturally searches the *next* batch — new information, not a repeat of the same query. Verified end-to-end: a 3-jurisdiction regulation query went from two "insufficient data" gaps and 0.30 confidence to full coverage of all three jurisdictions at 0.90 confidence, using the identical model and query, changing only this mechanism.

### Key design decisions (and why)

| Decision | Reasoning |
|---|---|
| Tools chosen by the planner, not `if/else` on keywords | Keyword-matching is a "fake agent" pitfall. The planner receives only tool *descriptions* and decides. |
| Evidence dedup via `difflib` text similarity, not embeddings | At this scale (typically 5–15 evidence items/query), embeddings add a dependency and cost without a meaningful quality gain. Would swap to embedding cosine-similarity if volume grew into the hundreds. |
| Relevance filtering has a safety fallback | If filtering would remove *all* evidence (a genuinely obscure query), the filter backs off and keeps everything unfiltered. A low-confidence report from mediocre evidence beats a broken one from zero evidence. |
| References taken directly from evidence URLs, never LLM-generated | Prevents hallucinated citations by construction — the report generator physically cannot invent a source that wasn't retrieved. |
| Sub-question batching via an offset, not separate "seen" tracking | One mechanism (`subquestion_offset`) solves both "search more than one sub-question" and "retry with new questions, not the same one" — no duplicate bookkeeping. |
| Memory is advisory, not authoritative | The planner is explicitly told past research "may or may not be useful" — a coarse lexical match (`find_similar`) can false-positive, so the LLM is left to judge relevance itself rather than trusting it blindly. |
| Report export is in-memory only, no server-side disk copy | Once `report_json` is stored in SQLite, a `reports_output/` folder on disk is a redundant second copy of the same content. The browser download is the export; SQLite is the one durable copy. |
| SQLite + raw `aiosqlite`, no ORM | Memory scope is narrow (query/timestamp/summary/full report) — an ORM would be overengineering here. |
| SSE for progress streaming, not WebSockets | One-directional progress updates don't need a bidirectional channel. |
| Retry-with-backoff scoped to 429/5xx only | Transient failures (rate limits, server errors) genuinely resolve on retry; permanent failures (bad API key) fail fast instead of wasting attempts. |

---

## Project structure

```
app/
├── main.py                    FastAPI app + lifespan (DB init/migration)
├── config.py                   Typed settings from .env
├── api/
│   └── routes.py                 /research, /research/stream (SSE),
│                                   /memory/recent, /memory/{id}, /export/{fmt}
├── agents/
│   ├── state.py                    Shared LangGraph state (TypedDict)
│   ├── graph.py                     Graph wiring + conditional edge logic
│   ├── planner.py                    Autonomous tool/scope decision + memory lookup
│   ├── tool_executor.py               Parallel fan-out across tools AND sub-questions
│   ├── evidence.py                     Dedup + rank + relevance filter
│   ├── reasoner.py                      Agreement/contradiction analysis
│   ├── report_generator.py               Structured report, grounded citations
│   └── prompts.py                         Centralized prompt templates
├── tools/                       ResearchTool ABC + Tavily/ArXiv/Scraper implementations
├── services/
│   ├── llm_client.py               Provider-agnostic (Gemini/OpenAI) structured-output
│   │                                 client, with retry-on-transient-failure
│   ├── memory_service.py            SQLite storage (full report + lexical similarity lookup)
│   └── report_service.py             In-memory Markdown/PDF generation, no disk I/O
├── models/schemas.py            All Pydantic contracts between layers
└── utils/logger.py
frontend/
├── index.html                  Structure only
├── styles.css                   Sidebar + conversation-thread layout
└── app.js                        History loading, streaming, export handling
```

---

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:
- `GEMINI_API_KEY` — free at https://aistudio.google.com/apikey
- `TAVILY_API_KEY` — free tier (1000 searches/month) at https://tavily.com

```bash
python run.py
```

Open `http://localhost:8000`.

> **A note on free-tier model quotas**: Gemini's per-model daily quotas vary significantly and change over time — some models are far more generous than others even within the same family. If you hit `429 RESOURCE_EXHAUSTED`, check the quota dashboard linked in the error message and consider switching `GEMINI_MODEL` in `.env` to a model with more daily headroom; no code changes are needed, it's a plain string in the config.

---

## API

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/research/stream` | SSE stream of live progress + final report. Body: `{"query": "..."}` |
| `POST` | `/api/research` | Synchronous variant, returns the final report JSON directly |
| `GET` | `/api/memory/recent?limit=10` | Recent research history (summary only) |
| `GET` | `/api/memory/{id}` | Full stored report for a past run — powers the sidebar's click-to-reopen |
| `POST` | `/api/export/{markdown\|pdf}` | Generates and streams a report file (body: report JSON from a prior call) |

---

## Known limitations / next steps

- **Deployment roadmap** — the backend is fully functional for local execution. Streamlit deployment is currently being finalized to provide a publicly accessible demonstration.
- **Database roadmap** — SQLite is intentionally used for the current assessment to keep the project lightweight and self-contained. Integration with MongoDB Atlas is in progress to support scalable persistence and future production-ready deployments.
- **Evidence dedup and memory-similarity lookup are both lexical, not semantic** — near-duplicate paraphrases, or semantically-related-but-differently-worded past queries, can slip past matching. Would move to embedding cosine-similarity at scale.
- **The scraper tool requires the planner to pass a real URL** as its search input; there's no automatic URL-discovery-then-scrape step yet.
- **Reports created before the memory schema was widened** (to store the full report, not just a summary) can't be reopened from history — `GET /api/memory/{id}` correctly returns 404 for those rather than erroring, but the underlying content genuinely wasn't persisted at the time.
- **No automated test suite** — verification during development was done via targeted manual scripts (mocked pipeline runs, boundary-condition checks on the confidence-loop and sub-question offset, live API smoke tests) rather than a committed test suite. These would be the first candidates for real `pytest` coverage in a follow-up pass.
- **Sub-question batch cap (default 3) trades off latency for coverage** — raising it searches more of the plan's decomposition per pass but increases per-query runtime and API usage; tune `MAX_SUBQUESTIONS_PER_BATCH` in `.env` if either constraint matters more for your use case.
