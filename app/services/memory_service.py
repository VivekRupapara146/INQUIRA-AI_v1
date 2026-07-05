"""
SQLite memory service.

Kept deliberately simple (raw aiosqlite, no ORM) -- the brief scopes memory
as "store previous research: query, timestamp, summary, references,
metadata" and explicitly lists "Large databases" under Features to Avoid.
An ORM would be overengineering for this scope.
"""

from __future__ import annotations

import json
from datetime import datetime

import aiosqlite

from app.config import get_settings
from app.models.schemas import ResearchMemoryRecord, ResearchReport
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    summary TEXT NOT NULL,
    references_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    report_json TEXT
);
"""


def _row_to_record(row) -> ResearchMemoryRecord:
    return ResearchMemoryRecord(
        id=row["id"],
        query=row["query"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
        summary=row["summary"],
        references=json.loads(row["references_json"]),
        metadata=json.loads(row["metadata_json"]),
    )


class MemoryService:
    def __init__(self):
        self._db_path = get_settings().sqlite_path

    async def init_db(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_SCHEMA)
            # Migration for DBs created before report_json existed -- CREATE
            # TABLE IF NOT EXISTS won't add a column to an already-existing
            # table, so this handles upgrading a DB from earlier in this
            # project without requiring anyone to delete inquira.db.
            try:
                await db.execute("ALTER TABLE research_memory ADD COLUMN report_json TEXT")
                await db.commit()
                logger.info("Migrated research_memory table: added report_json column")
            except aiosqlite.OperationalError:
                pass  # column already exists -- normal case after first migration
            await db.commit()

    async def save(self, report: ResearchReport) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "INSERT INTO research_memory "
                "(query, timestamp, summary, references_json, metadata_json, report_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    report.query,
                    report.generated_at.isoformat(),
                    report.executive_summary,
                    json.dumps(report.references),
                    json.dumps({"confidence_score": report.confidence_score}),
                    report.model_dump_json(),
                ),
            )
            await db.commit()
            return cursor.lastrowid

    async def get_by_id(self, record_id: int) -> ResearchReport | None:
        """
        Fetches the FULL report (not just the summary) for a past run --
        this is what lets a sidebar/history click redisplay the original
        report instead of re-running research from scratch.
        """
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            row = await db.execute_fetchall(
                "SELECT report_json FROM research_memory WHERE id = ?", (record_id,)
            )
            if not row or not row[0]["report_json"]:
                return None
            return ResearchReport.model_validate_json(row[0]["report_json"])

    async def get_recent(self, limit: int = 10) -> list[ResearchMemoryRecord]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT * FROM research_memory ORDER BY id DESC LIMIT ?", (limit,)
            )
            return [_row_to_record(row) for row in rows]

    async def find_similar(self, query: str, limit: int = 3) -> list[ResearchMemoryRecord]:
        """
        Lightweight relevant-history lookup for the "reuse historical context"
        requirement. Uses SQL LIKE on shared words rather than embeddings --
        consistent with the evidence-dedup tradeoff (difflib over embeddings)
        for MVP scope; swap to a vector store if this needs to scale.
        """
        terms = [t for t in query.lower().split() if len(t) > 3][:5]
        if not terms:
            return []

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            like_clauses = " OR ".join(["LOWER(query) LIKE ?"] * len(terms))
            params = [f"%{t}%" for t in terms]
            rows = await db.execute_fetchall(
                f"SELECT * FROM research_memory WHERE {like_clauses} ORDER BY id DESC LIMIT ?",
                (*params, limit),
            )
            return [_row_to_record(row) for row in rows]
