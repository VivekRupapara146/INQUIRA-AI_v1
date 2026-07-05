"""
API routes.

Design choice: research runs via Server-Sent Events (SSE), not a plain
request/response, because the brief explicitly wants the UI to show live
progress ("Planning research... Selecting tools... Searching..."). SSE is
simpler than WebSockets for a one-directional progress stream and needs no
extra client library.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse

from app.agents.graph import build_graph
from app.models.schemas import ResearchRequest
from app.services.memory_service import MemoryService
from app.services.report_service import ReportExportService
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

_memory = MemoryService()
_exporter = ReportExportService()

# Human-readable progress labels per internal stage key, per the brief's UX spec
_STAGE_LABELS = {
    "started": ("Planning research...", 5),
    "planning_complete": ("Selecting tools...", 20),
    "evidence_collected": ("Reading sources...", 50),
    "evidence_ranked": ("Ranking evidence...", 65),
    "reasoning_complete": ("Analyzing evidence...", 80),
    "report_complete": ("Generating report...", 95),
}


@router.post("/research/stream")
async def research_stream(request: ResearchRequest):
    """
    Streams progress events as the LangGraph executes, then a final event
    containing the full report. Uses astream_events under the hood so the
    UI gets real node-by-node visibility instead of a single blocking call.
    """

    async def event_generator():
        graph = build_graph()
        initial_state = {"query": request.query, "current_stage": "started", "errors": [], "iterations": 0, "subquestion_offset": 0}

        try:
            async for event in graph.astream(initial_state):
                # event is {node_name: partial_state}
                for node_name, node_state in event.items():
                    stage = node_state.get("current_stage", node_name)
                    label, percent = _STAGE_LABELS.get(stage, (f"Running {node_name}...", 50))
                    yield f"data: {json.dumps({'stage': stage, 'message': label, 'percent': percent})}\n\n"

                    if stage == "report_complete":
                        report = node_state["report"]
                        record_id = await _memory.save(report)
                        payload = report.model_dump(mode="json")
                        payload["_memory_id"] = record_id
                        yield f"data: {json.dumps({'stage': 'done', 'message': 'Complete', 'percent': 100, 'report': payload})}\n\n"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Research pipeline failed")
            yield f"data: {json.dumps({'stage': 'error', 'message': str(exc), 'percent': 0})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/research")
async def research_sync(request: ResearchRequest):
    """Non-streaming variant -- useful for programmatic/API-only clients."""
    from app.agents.graph import run_research

    final_state = await run_research(request.query)
    report = final_state.get("report")
    if report is None:
        raise HTTPException(status_code=500, detail="Research pipeline did not produce a report")

    await _memory.save(report)
    return report.model_dump(mode="json")


@router.get("/memory/recent")
async def memory_recent(limit: int = 10):
    records = await _memory.get_recent(limit=limit)
    return [r.model_dump(mode="json") for r in records]


@router.get("/memory/{record_id}")
async def memory_get_full(record_id: int):
    """Returns the FULL report for a past run -- used by the frontend's
    history/sidebar click to redisplay a report without re-running research."""
    report = await _memory.get_by_id(record_id)
    if report is None:
        raise HTTPException(status_code=404, detail="No stored report for that id")
    return report.model_dump(mode="json")


@router.post("/export/{fmt}")
async def export_report(fmt: str, report_json: dict):
    """
    fmt: 'markdown' or 'pdf'. Body is a ResearchReport as JSON (from a prior
    /research response). Generates in-memory and streams directly -- no
    server-side disk write, since SQLite (report_json column) is already the
    system's one durable copy of every report. This avoids a redundant
    second copy piling up in a local folder for content the user is about
    to download anyway.
    """
    from app.models.schemas import ResearchReport

    report = ResearchReport.model_validate(report_json)
    filename = _exporter.export_filename(report, "md" if fmt == "markdown" else "pdf")

    if fmt == "markdown":
        content = _exporter.to_markdown(report)
        return Response(
            content=content,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    elif fmt == "pdf":
        content = _exporter.render_pdf_bytes(report)
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    else:
        raise HTTPException(status_code=400, detail="fmt must be 'markdown' or 'pdf'")
