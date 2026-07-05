"""
Report export service: Markdown (always) and PDF (via reportlab).

Kept separate from the report_generator AGENT node deliberately -- generating
the report's CONTENT is an LLM/reasoning concern (agents/report_generator.py),
while rendering that content to a file FORMAT is a pure I/O concern. Mixing
them would violate single-responsibility.

Generates in-memory only (no disk writes) -- earlier versions also saved a
copy to a local reports_output/ folder, but since ResearchReport is now
stored in full in SQLite (see memory_service.py's report_json column), a
second on-disk copy was pure redundancy: same content, two locations, no
added capability. The browser download IS the export; SQLite is the
system's one durable copy.
"""

from __future__ import annotations

import io
import re

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, ListFlowable, ListItem

from app.models.schemas import ResearchReport
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


class ReportExportService:
    def export_filename(self, report: ResearchReport, extension: str) -> str:
        """
        Timestamped filename for the Content-Disposition header -- includes
        report.generated_at so a browser saving two exports of the same
        query won't silently overwrite one (browsers auto-suffix "(1)" on
        collision, but a distinct name avoids relying on that behavior).
        """
        ts = report.generated_at.strftime("%Y%m%d-%H%M%S")
        return f"{_slugify(report.query)}_{ts}.{extension}"

    def to_markdown(self, report: ResearchReport) -> str:
        lines = [
            f"# Research Report: {report.query}",
            f"*Generated {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')} "
            f"| Confidence: {report.confidence_score:.0%}*",
            "",
            "## Executive Summary",
            report.executive_summary,
            "",
            "## Key Findings",
            *[f"- {f}" for f in report.key_findings],
            "",
        ]

        for section in report.detailed_analysis:
            lines += [f"## {section.heading}", section.content, ""]

        if report.comparisons:
            lines += ["## Comparisons", report.comparisons, ""]

        if report.statistics:
            lines += ["## Key Statistics", *[f"- {s}" for s in report.statistics], ""]

        if report.actionable_insights:
            lines += ["## Actionable Insights", *[f"- {i}" for i in report.actionable_insights], ""]

        lines += ["## References", *[f"- {r}" for r in report.references]]

        return "\n".join(lines)

    def render_pdf_bytes(self, report: ResearchReport) -> bytes:
        """Builds the PDF into an in-memory buffer -- no file ever touches disk."""
        buffer = io.BytesIO()

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("TitleX", parent=styles["Title"], fontSize=18)
        heading_style = styles["Heading2"]
        body_style = styles["BodyText"]

        doc = SimpleDocTemplate(buffer, pagesize=LETTER, topMargin=0.75 * inch, bottomMargin=0.75 * inch)
        story = [
            Paragraph(f"Research Report: {report.query}", title_style),
            Paragraph(
                f"Confidence: {report.confidence_score:.0%} | "
                f"Generated {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
                body_style,
            ),
            Spacer(1, 0.2 * inch),
            Paragraph("Executive Summary", heading_style),
            Paragraph(report.executive_summary, body_style),
            Spacer(1, 0.15 * inch),
            Paragraph("Key Findings", heading_style),
            ListFlowable([ListItem(Paragraph(f, body_style)) for f in report.key_findings], bulletType="bullet"),
        ]

        for section in report.detailed_analysis:
            story += [
                Spacer(1, 0.15 * inch),
                Paragraph(section.heading, heading_style),
                Paragraph(section.content, body_style),
            ]

        if report.actionable_insights:
            story += [
                Spacer(1, 0.15 * inch),
                Paragraph("Actionable Insights", heading_style),
                ListFlowable(
                    [ListItem(Paragraph(i, body_style)) for i in report.actionable_insights],
                    bulletType="bullet",
                ),
            ]

        story += [
            Spacer(1, 0.15 * inch),
            Paragraph("References", heading_style),
            ListFlowable(
                [ListItem(Paragraph(r, body_style)) for r in report.references], bulletType="bullet"
            ),
        ]

        doc.build(story)
        return buffer.getvalue()
