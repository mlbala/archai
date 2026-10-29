"""Render ArchAI Markdown documents to PDF with embedded vector diagrams (ReportLab)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from functools import partial
from html import escape
from pathlib import Path
from typing import Any

from archai.compilers.scene import Scene, plain, to_drawing

DIAGRAM_MARKER = re.compile(r"<!--\s*archai:diagram\s+([\w.-]+)\s*-->")
ACCENT = "#1d4ed8"


def _inline(text: str) -> str:
    """Escape XML and convert a safe subset of Markdown inline syntax to ReportLab markup."""
    value = escape(plain(text), quote=False)
    value = re.sub(r"`([^`]+)`", r'<font face="Courier" size="8">\1</font>', value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"(?<![\w*])\*([^*\s][^*]*)\*(?![\w*])", r"<i>\1</i>", value)
    value = re.sub(r"(?<![\w_])_([^_\s][^_]*)_(?![\w_])", r"<i>\1</i>", value)
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", value)
    return value.replace("\\|", "|")


def _split_row(line: str) -> list[str]:
    body = line.strip().strip("|")
    cells: list[str] = []
    current = ""
    index = 0
    while index < len(body):
        char = body[index]
        if char == "\\" and index + 1 < len(body) and body[index + 1] == "|":
            current += "\\|"
            index += 2
            continue
        if char == "|":
            cells.append(current.strip())
            current = ""
        else:
            current += char
        index += 1
    cells.append(current.strip())
    return cells


def _column_widths(weights: list[int], total_width: float, minimum: float = 42.0) -> list[float]:
    """Proportional column widths with a readable minimum per column."""
    if not weights:
        return []
    if minimum * len(weights) >= total_width:
        return [total_width / len(weights)] * len(weights)
    widths = [total_width * weight / sum(weights) for weight in weights]
    for _ in range(len(weights)):
        narrow = [index for index, width in enumerate(widths) if width < minimum]
        if not narrow:
            break
        fixed = minimum * len(narrow)
        rest = [index for index in range(len(widths)) if index not in narrow]
        rest_weight = sum(weights[index] for index in rest) or 1
        for index in narrow:
            widths[index] = minimum
        for index in rest:
            widths[index] = (total_width - fixed) * weights[index] / rest_weight
    return widths


def render_pdf(
    markdown: str,
    path: Path,
    *,
    title: str,
    project: str,
    diagrams: dict[str, Scene],
    subtitle: str = "",
    cover_rows: list[tuple[str, str]] | None = None,
) -> None:
    from reportlab.lib import colors  # type: ignore[import-untyped]
    from reportlab.lib.enums import TA_LEFT  # type: ignore[import-untyped]
    from reportlab.lib.pagesizes import A4, landscape  # type: ignore[import-untyped]
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # type: ignore[import-untyped]
    from reportlab.lib.units import mm  # type: ignore[import-untyped]
    from reportlab.pdfgen import canvas  # type: ignore[import-untyped]
    from reportlab.platypus import (  # type: ignore[import-untyped]
        BaseDocTemplate,
        CondPageBreak,
        Frame,
        KeepTogether,
        NextPageTemplate,
        PageBreak,
        PageTemplate,
        Paragraph,
        Preformatted,
        Spacer,
        Table,
        TableStyle,
    )

    styles = getSampleStyleSheet()
    base = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.2,
        leading=12.6,
        alignment=TA_LEFT,
        spaceAfter=3,
    )
    small = ParagraphStyle("Small", parent=base, fontSize=7.6, leading=9.6, spaceAfter=0)
    small_bold = ParagraphStyle(
        "SmallBold", parent=small, fontName="Helvetica-Bold", textColor=colors.white
    )
    caption = ParagraphStyle(
        "Caption",
        parent=base,
        fontSize=8,
        textColor=colors.HexColor("#475569"),
        fontName="Helvetica-Oblique",
    )
    quote = ParagraphStyle(
        "Quote",
        parent=base,
        backColor=colors.HexColor("#f1f5f9"),
        borderPadding=(5, 6, 5, 6),
        leftIndent=6,
        rightIndent=6,
        textColor=colors.HexColor("#334155"),
        spaceBefore=4,
        spaceAfter=8,
    )
    bullet = ParagraphStyle("Bullet", parent=base, leftIndent=12, bulletIndent=3, spaceAfter=1.5)
    headings = {
        1: ParagraphStyle(
            "H1",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#0f172a"),
            spaceBefore=6,
            spaceAfter=10,
        ),
        2: ParagraphStyle(
            "H2",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13.5,
            leading=17,
            textColor=colors.HexColor(ACCENT),
            spaceBefore=12,
            spaceAfter=6,
        ),
        3: ParagraphStyle(
            "H3",
            parent=styles["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#0f172a"),
            spaceBefore=9,
            spaceAfter=4,
        ),
        4: ParagraphStyle(
            "H4",
            parent=styles["Heading4"],
            fontName="Helvetica-Bold",
            fontSize=9.8,
            leading=13,
            spaceBefore=6,
            spaceAfter=3,
        ),
    }
    code = ParagraphStyle(
        "Code",
        parent=base,
        fontName="Courier",
        fontSize=7.2,
        leading=8.8,
        backColor=colors.HexColor("#f8fafc"),
        borderPadding=4,
    )

    portrait = A4
    wide = landscape(A4)
    margin = 16 * mm
    portrait_width = portrait[0] - 2 * margin
    wide_width = wide[0] - 2 * margin

    def footer(pdf: Any, doc: Any) -> None:
        pdf.saveState()
        width = pdf._pagesize[0]
        pdf.setStrokeColor(colors.HexColor("#cbd5e1"))
        pdf.line(margin, 11 * mm, width - margin, 11 * mm)
        pdf.setFont("Helvetica", 7.5)
        pdf.setFillColor(colors.HexColor("#475569"))
        pdf.drawString(margin, 7 * mm, f"ArchAI · {project} · {title} · design assets only")
        pdf.drawRightString(width - margin, 7 * mm, f"Page {doc.page}")
        pdf.restoreState()

    document = BaseDocTemplate(
        str(path),
        pagesize=portrait,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=title,
        author="",
        subject=f"ArchAI design for {project}",
        creator="ArchAI",
    )
    document.addPageTemplates(
        [
            PageTemplate(
                id="portrait",
                frames=[Frame(margin, 16 * mm, portrait_width, portrait[1] - 32 * mm, id="p")],
                pagesize=portrait,
                onPage=footer,
            ),
            PageTemplate(
                id="wide",
                frames=[Frame(margin, 16 * mm, wide_width, wide[1] - 32 * mm, id="w")],
                pagesize=wide,
                onPage=footer,
            ),
        ]
    )

    def para(text: str, style: Any, **kwargs: Any) -> Any:
        try:
            return Paragraph(text, style, **kwargs)
        except ValueError:
            plain = re.sub(r"<[^>]+>", "", text)
            return Paragraph(plain, style, **kwargs)

    class _Story(list[Any]):
        """Flowables; returns to portrait pages lazily after landscape diagrams."""

        wide = False

        def append(self, item: Any) -> None:
            if self.wide:
                super().append(NextPageTemplate("portrait"))
                super().append(PageBreak())
                self.wide = False
            super().append(item)

        def raw(self, item: Any) -> None:
            super().append(item)

    story = _Story()
    lines = markdown.splitlines()
    headings_found = [
        line[3:].strip() for line in lines if line.startswith("## ") and not line.startswith("###")
    ]

    # Cover page
    story.append(Spacer(1, 40 * mm))
    story.append(
        Paragraph(
            "ArchAI",
            ParagraphStyle(
                "Brand",
                parent=base,
                fontSize=11,
                textColor=colors.HexColor(ACCENT),
                fontName="Helvetica-Bold",
            ),
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(
        Paragraph(
            escape(title), ParagraphStyle("Cover", parent=headings[1], fontSize=26, leading=31)
        )
    )
    if subtitle:
        story.append(
            Paragraph(
                escape(plain(subtitle)), ParagraphStyle("Sub", parent=base, fontSize=12, leading=16)
            )
        )
    story.append(Spacer(1, 10 * mm))
    rows = [
        ("Project", project),
        ("Generated", datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")),
        *(cover_rows or []),
    ]
    cover = Table(
        [
            [Paragraph(f"<b>{escape(k)}</b>", base), Paragraph(escape(plain(v)), base)]
            for k, v in rows
        ],
        colWidths=[42 * mm, portrait_width - 42 * mm],
    )
    cover.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(cover)
    story.append(Spacer(1, 12 * mm))
    story.append(
        Paragraph(
            "This document is a reviewed design artifact. It does not deploy infrastructure or prove "
            "the availability, quota, or price of any cloud or model service.",
            quote,
        )
    )
    if len(headings_found) > 2:
        story.append(PageBreak())
        story.append(Paragraph("Contents", headings[1]))
        for number, entry in enumerate(headings_found, 1):
            story.append(Paragraph(f"{number}. {_inline(entry)}", base))
    story.append(PageBreak())

    pending_diagram: str | None = None
    paragraph: list[str] = []
    first_h1 = True

    def flush_paragraph() -> None:
        if paragraph:
            story.append(para(_inline(" ".join(paragraph)), base))
            paragraph.clear()

    def add_table(rows_raw: list[list[str]]) -> None:
        if not rows_raw:
            return
        header, body = rows_raw[0], rows_raw[1:]
        columns = len(header)
        if columns >= 7 and body:
            _add_record_table(header, body)
            return
        weights = [
            max(4, min(60, max(len(row[i]) if i < len(row) else 0 for row in rows_raw)))
            for i in range(columns)
        ]
        widths = _column_widths(weights, portrait_width)
        data = [[para(_inline(cell), small_bold) for cell in header]]
        for row in body:
            padded = [*row, *[""] * (columns - len(row))][:columns]
            data.append([para(_inline(cell), small) for cell in padded])
        grid = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
        grid.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f8fafc")],
                    ),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(grid)
        story.append(Spacer(1, 3 * mm))

    def _add_record_table(header: list[str], body: list[list[str]]) -> None:
        """Wide tables become one labeled record per row so columns stay readable on A4."""
        label_width = 38 * mm
        value_width = portrait_width - label_width
        banner = ParagraphStyle("RecordBanner", parent=small_bold, fontSize=8, leading=10)
        label = ParagraphStyle(
            "RecordLabel",
            parent=small,
            fontName="Helvetica-Bold",
            textColor=colors.HexColor("#1e3a8a"),
        )
        for row in body:
            padded = [*row, *[""] * (len(header) - len(row))][: len(header)]
            title = padded[0] or "Record"
            data: list[list[Any]] = [[para(_inline(title), banner), ""]]
            pairs = list(zip(header[1:], padded[1:], strict=False))
            if not pairs:
                pairs = [(header[0], title)]
            for name, value in pairs:
                data.append([para(_inline(name), label), para(_inline(value or "—"), small)])
            grid = Table(data, colWidths=[label_width, value_width], hAlign="LEFT")
            grid.setStyle(
                TableStyle(
                    [
                        ("SPAN", (0, 0), (-1, 0)),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
                        ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#f8fafc")),
                        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
                    ]
                )
            )
            story.append(grid)
            story.append(Spacer(1, 2.2 * mm))

    def add_diagram(key: str) -> bool:
        scene = diagrams.get(key)
        if scene is None:
            return False
        frame_h = portrait[1] - 32 * mm - 30
        if not is_wide(scene):
            drawing = to_drawing(scene, portrait_width, frame_h * 0.75)
            story.append(KeepTogether([drawing, Spacer(1, 2 * mm)]))
            return True
        heading_text, caption_text = wide_meta.get(key, (scene.title, ""))
        if not story.wide:
            story.raw(NextPageTemplate("wide"))
        story.raw(PageBreak())
        story.raw(para(_inline(heading_text), headings[3]))
        story.raw(to_drawing(scene, wide_width, wide[1] - 32 * mm - 56))
        if caption_text:
            story.raw(para(_inline(caption_text), caption))
        story.wide = True
        return True

    def is_wide(scene: Scene) -> bool:
        return bool(scene.width > portrait_width * 1.25)

    # Pre-pass: wide diagrams carry their heading and caption onto the landscape page.
    wide_meta: dict[str, tuple[str, str]] = {}
    skip_lines: set[int] = set()
    for number, text in enumerate(lines):
        found = DIAGRAM_MARKER.search(text.strip())
        if not found or found.group(1) not in diagrams or not is_wide(diagrams[found.group(1)]):
            continue
        before = number - 1
        while before >= 0 and not lines[before].strip():
            before -= 1
        heading_line = ""
        if before >= 0 and lines[before].lstrip().startswith("#"):
            heading_line = lines[before].strip().lstrip("#").strip()
            skip_lines.add(before)
        after = number + 1
        if after < len(lines) and lines[after].strip().startswith("```"):
            after += 1
            while after < len(lines) and not lines[after].strip().startswith("```"):
                after += 1
            after += 1
        while after < len(lines) and not lines[after].strip():
            after += 1
        caption_line = ""
        candidate = lines[after].strip() if after < len(lines) else ""
        if candidate.startswith("_") and candidate.endswith("_") and len(candidate) > 2:
            caption_line = candidate
            skip_lines.add(after)
        wide_meta[found.group(1)] = (
            heading_line or diagrams[found.group(1)].title,
            caption_line,
        )

    index = 0
    while index < len(lines):
        if index in skip_lines:
            index += 1
            continue
        raw = lines[index]
        line = raw.rstrip()
        stripped = line.strip()
        marker = DIAGRAM_MARKER.search(stripped)
        if marker:
            flush_paragraph()
            pending_diagram = marker.group(1)
            index += 1
            continue
        if stripped.startswith("```"):
            flush_paragraph()
            language = stripped[3:].strip()
            block: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                block.append(lines[index])
                index += 1
            index += 1
            if language == "mermaid" and pending_diagram and add_diagram(pending_diagram):
                pending_diagram = None
                continue
            pending_diagram = None
            wrapped: list[str] = []
            for item in block:
                while len(item) > 110:
                    wrapped.append(item[:110])
                    item = "    " + item[110:]
                wrapped.append(item)
            story.append(Preformatted(plain("\n".join(wrapped)), code))
            story.append(Spacer(1, 2 * mm))
            continue
        if not stripped:
            flush_paragraph()
            index += 1
            continue
        if stripped.startswith("|"):
            flush_paragraph()
            rows_raw: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                row = _split_row(lines[index])
                if not all(re.fullmatch(r":?-{3,}:?", cell or "---") for cell in row):
                    rows_raw.append(row)
                index += 1
            add_table(rows_raw)
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            flush_paragraph()
            level = min(4, len(heading.group(1)))
            text = heading.group(2)
            if level == 1:
                if not first_h1:
                    story.append(PageBreak())
                first_h1 = False
            elif level == 2:
                story.append(CondPageBreak(40 * mm))
            story.append(para(_inline(text), headings[level]))
            index += 1
            continue
        if stripped == "---":
            flush_paragraph()
            story.append(Spacer(1, 3 * mm))
            index += 1
            continue
        if stripped.startswith("> "):
            flush_paragraph()
            story.append(para(_inline(stripped[2:]), quote))
            index += 1
            continue
        bullet_match = re.match(r"^(\s*)[-*]\s+(.*)$", line)
        number_match = re.match(r"^(\s*)(\d+)\.\s+(.*)$", line)
        if bullet_match:
            flush_paragraph()
            depth = len(bullet_match.group(1)) // 2
            style = ParagraphStyle(
                f"B{depth}", parent=bullet, leftIndent=12 + depth * 10, bulletIndent=3 + depth * 10
            )
            story.append(para(_inline(bullet_match.group(2)), style, bulletText="•"))
            index += 1
            continue
        if number_match:
            flush_paragraph()
            story.append(
                para(_inline(number_match.group(3)), bullet, bulletText=f"{number_match.group(2)}.")
            )
            index += 1
            continue
        if stripped.startswith("_") and stripped.endswith("_") and len(stripped) > 2:
            flush_paragraph()
            story.append(para(_inline(stripped), caption))
            index += 1
            continue
        paragraph.append(stripped)
        index += 1
    flush_paragraph()
    document.build(story, canvasmaker=partial(canvas.Canvas, invariant=1))
