"""Deterministic diagram scenes rendered as PDF drawings. Diagram files are Mermaid only."""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from typing import Any, Literal

FONT = "Helvetica"
PALETTE = {
    "ink": "#0f172a",
    "muted": "#475569",
    "line": "#64748b",
    "lane": "#f1f5f9",
    "lane_border": "#cbd5e1",
    "canvas": "#ffffff",
    "client": "#fef3c7",
    "identity": "#fde68a",
    "gateway": "#e0e7ff",
    "application": "#dbeafe",
    "policy": "#ede9fe",
    "ai": "#dcfce7",
    "model": "#bbf7d0",
    "data": "#fce7f3",
    "queue": "#ffe4e6",
    "worker": "#fae8ff",
    "ops": "#e2e8f0",
    "note": "#fefce8",
}
STROKES = {
    "client": "#b45309",
    "identity": "#b45309",
    "gateway": "#4338ca",
    "application": "#1d4ed8",
    "policy": "#6d28d9",
    "ai": "#15803d",
    "model": "#166534",
    "data": "#be185d",
    "queue": "#be123c",
    "worker": "#a21caf",
    "ops": "#475569",
    "note": "#a16207",
}


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float
    lines: list[str]
    style: str = "application"
    font_size: float = 11
    bold_first: bool = True
    radius: float = 8
    dashed: bool = False
    fill: str | None = None
    stroke: str | None = None
    align: Literal["center", "top"] = "center"


@dataclass
class Text:
    x: float
    y: float
    text: str
    size: float = 11
    color: str = PALETTE["ink"]
    bold: bool = False
    anchor: Literal["start", "middle", "end"] = "start"


@dataclass
class Line:
    points: list[tuple[float, float]]
    color: str = PALETTE["line"]
    width: float = 1.4
    dashed: bool = False
    arrow: bool = True
    label: str | None = None
    label_at: tuple[float, float] | None = None


@dataclass
class Scene:
    width: float
    height: float
    title: str
    items: list[Box | Text | Line] = field(default_factory=list)


GLYPHS = str.maketrans(
    {
        "→": "->",
        "←": "<-",
        "↔": "<->",
        "≤": "<=",
        "≥": ">=",
        "≈": "~",
        "✔": "v",
        "✖": "x",
        "·": "|",
        "—": "-",
        "–": "-",
        "…": "...",
    }
)


def plain(text: str) -> str:
    """Replace glyphs missing from the standard PDF fonts."""
    return text.translate(GLYPHS)


def text_width(text: str, size: float) -> float:
    try:
        from reportlab.pdfbase.pdfmetrics import stringWidth  # type: ignore[import-untyped]

        return float(stringWidth(text, FONT, size))
    except ImportError:  # pragma: no cover - reportlab is a core dependency
        return len(text) * size * 0.55


def wrap(text: str, width_px: float, size: float, max_lines: int = 4) -> list[str]:
    chars = max(6, int(width_px / (size * 0.56)))
    lines = textwrap.wrap(text, chars, break_long_words=True) or [""]
    if len(lines) > max_lines:
        lines = [*lines[: max_lines - 1], lines[max_lines - 1][: max(1, chars - 1)] + "…"]
    return lines


def _box_lines(box: Box) -> list[tuple[str, float]]:
    leading = box.font_size * 1.3
    if box.align == "top":
        start = box.y + box.font_size + 8
    else:
        start = box.y + box.h / 2 - (len(box.lines) - 1) * leading / 2 + box.font_size * 0.35
    return [(line, start + index * leading) for index, line in enumerate(box.lines)]


# ---------------------------------------------------------------- ReportLab


def to_drawing(scene: Scene, max_width: float, max_height: float) -> Any:
    """Vector drawing for PDF embedding, scaled to fit the frame."""
    from reportlab.graphics.shapes import (  # type: ignore[import-untyped]
        Drawing,
        Group,
        Polygon,
        PolyLine,
        Rect,
        String,
    )
    from reportlab.lib.colors import HexColor  # type: ignore[import-untyped]

    scale = min(1.0, max_width / scene.width, max_height / scene.height)
    drawing = Drawing(scene.width * scale, scene.height * scale)
    group = Group()
    height = scene.height

    def flip(y: float) -> float:
        return height - y

    for item in scene.items:
        if isinstance(item, Line):
            points: list[float] = []
            for x, y in item.points:
                points.extend([x, flip(y)])
            group.add(
                PolyLine(
                    points,
                    strokeColor=HexColor(item.color),
                    strokeWidth=item.width,
                    strokeDashArray=[5, 4] if item.dashed else None,
                )
            )
            if item.arrow and len(item.points) >= 2:
                (x1, y1), (x2, y2) = item.points[-2], item.points[-1]
                length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 or 1
                ux, uy = (x2 - x1) / length, (y2 - y1) / length
                size = 7.0
                tip = (x2, flip(y2))
                left = (x2 - ux * size - uy * size * 0.45, flip(y2 - uy * size + ux * size * 0.45))
                right = (x2 - ux * size + uy * size * 0.45, flip(y2 - uy * size - ux * size * 0.45))
                group.add(
                    Polygon(
                        [*tip, *left, *right],
                        fillColor=HexColor(item.color),
                        strokeColor=HexColor(item.color),
                        strokeWidth=0.5,
                    )
                )
    for item in scene.items:
        if isinstance(item, Box):
            fill = item.fill or PALETTE.get(item.style, PALETTE["application"])
            stroke = item.stroke or STROKES.get(item.style, PALETTE["line"])
            group.add(
                Rect(
                    item.x,
                    flip(item.y + item.h),
                    item.w,
                    item.h,
                    rx=item.radius,
                    ry=item.radius,
                    fillColor=HexColor(fill),
                    strokeColor=HexColor(stroke),
                    strokeWidth=1.1,
                    strokeDashArray=[6, 4] if item.dashed else None,
                )
            )
            for index, (line, ly) in enumerate(_box_lines(item)):
                group.add(
                    String(
                        item.x + item.w / 2,
                        flip(ly),
                        plain(line),
                        fontName="Helvetica-Bold" if index == 0 and item.bold_first else FONT,
                        fontSize=item.font_size,
                        fillColor=HexColor(PALETTE["ink"]),
                        textAnchor="middle",
                    )
                )
        elif isinstance(item, Text):
            group.add(
                String(
                    item.x,
                    flip(item.y),
                    plain(item.text),
                    fontName="Helvetica-Bold" if item.bold else FONT,
                    fontSize=item.size,
                    fillColor=HexColor(item.color),
                    textAnchor=item.anchor,
                )
            )
    for item in scene.items:
        if isinstance(item, Line) and item.label and item.label_at:
            lx, ly = item.label_at
            width = text_width(item.label, 8.5) + 6
            group.add(
                Rect(
                    lx - width / 2,
                    flip(ly + 4),
                    width,
                    12,
                    fillColor=HexColor("#ffffff"),
                    strokeColor=None,
                )
            )
            group.add(
                String(
                    lx,
                    flip(ly + 1),
                    plain(item.label),
                    fontName=FONT,
                    fontSize=8.5,
                    fillColor=HexColor(PALETTE["muted"]),
                    textAnchor="middle",
                )
            )
    group.scale(scale, scale)
    drawing.add(group)
    return drawing


# ---------------------------------------------------------------- layouts


@dataclass
class LayoutNode:
    id: str
    label: str
    sublabel: str | None
    column: int
    style: str


@dataclass
class LayoutEdge:
    source: str
    target: str
    label: str | None = None
    dashed: bool = False


def layered_scene(
    title: str,
    nodes: list[LayoutNode],
    edges: list[LayoutEdge],
    column_titles: list[str] | None = None,
    node_width: float = 168,
    gap: float = 64,
) -> Scene:
    """Columns of nodes with orthogonal connectors routed through inter-column channels."""
    columns = sorted({node.column for node in nodes})
    index = {column: position for position, column in enumerate(columns)}
    top = 58.0
    margin = 24.0
    lane_width = node_width + gap
    heights: dict[str, float] = {}
    wrapped: dict[str, list[str]] = {}
    for node in nodes:
        lines = wrap(node.label, node_width - 16, 11, 3)
        if node.sublabel:
            lines += wrap(node.sublabel, node_width - 16, 9.5, 2)
        wrapped[node.id] = lines
        heights[node.id] = max(46.0, 16 + len(lines) * 14.0)
    positions: dict[str, tuple[float, float]] = {}
    column_bottom: dict[int, float] = {}
    for column in columns:
        y = top + 16
        for node in [item for item in nodes if item.column == column]:
            x = margin + index[column] * lane_width + gap / 2
            positions[node.id] = (x, y)
            y += heights[node.id] + 22
        column_bottom[column] = y
    body_bottom = max(column_bottom.values(), default=top + 60)
    corridor_count = 0
    width = margin * 2 + len(columns) * lane_width
    scene = Scene(width=width, height=0, title=title)
    for column in columns:
        x = margin + index[column] * lane_width + 6
        scene.items.append(
            Box(
                x=x,
                y=top - 22,
                w=lane_width - 12,
                h=body_bottom - top + 30,
                lines=[],
                fill=PALETTE["lane"],
                stroke=PALETTE["lane_border"],
                radius=10,
            )
        )
        if column_titles and column < len(column_titles):
            scene.items.append(
                Text(
                    x + (lane_width - 12) / 2,
                    top - 6,
                    column_titles[column],
                    size=11,
                    color=PALETTE["muted"],
                    bold=True,
                    anchor="middle",
                )
            )
    by_id = {node.id: node for node in nodes}
    connectors: list[Line] = []
    placed: list[tuple[float, float]] = []
    corridor_base = body_bottom + 20
    for number, edge in enumerate(edges):
        if edge.source not in positions or edge.target not in positions:
            continue
        sx, sy = positions[edge.source]
        tx, ty = positions[edge.target]
        sh, th = heights[edge.source], heights[edge.target]
        s_col, t_col = index[by_id[edge.source].column], index[by_id[edge.target].column]
        offset = ((number % 5) - 2) * 4.0
        smid = sy + sh / 2 + offset / 2
        tmid = ty + th / 2 + offset / 2
        dashed = edge.dashed
        label_at: tuple[float, float] | None
        if t_col == s_col + 1:
            channel = sx + node_width + gap / 2 + offset
            points = [(sx + node_width, smid), (channel, smid), (channel, tmid), (tx, tmid)]
            label_at = (
                (channel, (smid + tmid) / 2)
                if abs(smid - tmid) > 30
                else (
                    (sx + node_width + tx) / 2,
                    smid - 6,
                )
            )
        elif t_col == s_col:
            channel = sx + node_width + 14 + abs(offset)
            points = [
                (sx + node_width, smid),
                (channel, smid),
                (channel, tmid),
                (tx + node_width, tmid),
            ]
            label_at = (channel, (smid + tmid) / 2)
        elif t_col > s_col:
            corridor = corridor_base + (corridor_count % 8) * 9
            corridor_count += 1
            exit_x = sx + node_width + gap / 2 + offset
            entry_x = tx - gap / 2 + offset
            points = [
                (sx + node_width, smid),
                (exit_x, smid),
                (exit_x, corridor),
                (entry_x, corridor),
                (entry_x, tmid),
                (tx, tmid),
            ]
            label_at = None
        else:
            corridor = corridor_base + (corridor_count % 8) * 9
            corridor_count += 1
            exit_x = sx - gap / 2 + offset
            entry_x = tx + node_width + gap / 2 + offset
            if t_col == s_col - 1:
                points = [(sx, smid), (exit_x, smid), (exit_x, tmid), (tx + node_width, tmid)]
                label_at = (exit_x, (smid + tmid) / 2)
            else:
                points = [
                    (sx, smid),
                    (exit_x, smid),
                    (exit_x, corridor),
                    (entry_x, corridor),
                    (entry_x, tmid),
                    (tx + node_width, tmid),
                ]
                label_at = None
        if label_at is not None and edge.label:
            lx, ly = label_at
            for _ in range(6):
                if not any(abs(ly - uy) < 13 and abs(lx - ux) < 70 for ux, uy in placed):
                    break
                ly += 13
            label_at = (lx, ly)
            placed.append(label_at)
        connectors.append(
            Line(
                points=points,
                dashed=dashed,
                color="#94a3b8" if dashed else PALETTE["line"],
                label=edge.label[:28] if edge.label else None,
                label_at=label_at,
            )
        )
    scene.items.extend(connectors)
    for node in nodes:
        x, y = positions[node.id]
        scene.items.append(
            Box(
                x=x,
                y=y,
                w=node_width,
                h=heights[node.id],
                lines=wrapped[node.id],
                style=node.style,
                font_size=10.5,
            )
        )
    scene.height = corridor_base + min(corridor_count, 8) * 9 + 24
    return scene


def sequence_scene(
    title: str,
    participants: list[tuple[str, str, str]],
    messages: list[tuple[str, str, str, bool]],
) -> Scene:
    """participants: (id, label, style); messages: (source, target, label, dashed)."""
    column = 150.0
    margin = 20.0
    head_h = 40.0
    x_of = {
        pid: margin + index * column + column / 2 for index, (pid, _, _) in enumerate(participants)
    }
    width = margin * 2 + column * len(participants)
    row = 40.0
    body_top = margin + head_h + 24
    height = body_top + row * len(messages) + 30
    scene = Scene(width=width, height=height, title=title)
    for pid, label, style in participants:
        x = x_of[pid]
        scene.items.append(
            Line(
                points=[(x, margin + head_h), (x, height - 12)],
                dashed=True,
                arrow=False,
                color="#cbd5e1",
                width=1,
            )
        )
        scene.items.append(
            Box(
                x=x - column / 2 + 8,
                y=margin,
                w=column - 16,
                h=head_h,
                lines=wrap(label, column - 28, 10.5, 2),
                style=style,
                font_size=10.5,
            )
        )
    for number, (source, target, label, dashed) in enumerate(messages):
        if source not in x_of or target not in x_of:
            continue
        y = body_top + number * row + 12
        x1, x2 = x_of[source], x_of[target]
        caption = f"{number + 1}. {label}"
        if x1 == x2:
            points = [(x1, y - 6), (x1 + 34, y - 6), (x1 + 34, y + 8), (x1 + 4, y + 8)]
            scene.items.append(Line(points=points, dashed=dashed))
            scene.items.append(Text(x1 + 40, y + 4, caption[:60], size=9, color=PALETTE["ink"]))
            continue
        scene.items.append(Line(points=[(x1, y), (x2 + (-4 if x2 > x1 else 4), y)], dashed=dashed))
        mid = (x1 + x2) / 2
        span = max(120.0, abs(x2 - x1) - 10)
        caption_lines = wrap(caption, span, 9, 2)
        for offset, text in enumerate(reversed(caption_lines)):
            scene.items.append(
                Text(mid, y - 5 - offset * 11, text, size=9, color=PALETTE["ink"], anchor="middle")
            )
    return scene


def group_scene(
    title: str,
    groups: list[tuple[str, list[tuple[str, str]], str]],
    outer_label: str | None,
    left: list[tuple[str, str]] | None = None,
    right: list[tuple[str, str, str]] | None = None,
) -> Scene:
    """Deployment view: groups of resources inside a cloud boundary, plus outside actors."""
    card_w, card_h, gap = 170.0, 44.0, 12.0
    margin = 24.0
    side_w = 160.0
    group_w = card_w + 24
    inner_x = margin + (side_w + 30 if left else 0)
    max_cards = max((len(items) for _, items, _ in groups), default=1)
    group_h = 40 + max_cards * (card_h + gap)
    boundary_w = len(groups) * (group_w + 14) + 26
    width = inner_x + boundary_w + (side_w + 30 if right else 0) + margin
    height = margin + 36 + group_h + 40
    scene = Scene(width=width, height=height, title=title)
    boundary_y = margin
    scene.items.append(
        Box(
            inner_x,
            boundary_y,
            boundary_w,
            group_h + 56,
            [],
            fill="#f8fafc",
            stroke="#94a3b8",
            dashed=True,
            radius=12,
        )
    )
    if outer_label:
        scene.items.append(
            Text(
                inner_x + 14,
                boundary_y + 20,
                outer_label,
                size=12,
                bold=True,
                color=PALETTE["muted"],
            )
        )
    centers: dict[str, tuple[float, float]] = {}
    for number, (name, items, style) in enumerate(groups):
        gx = inner_x + 14 + number * (group_w + 14)
        gy = boundary_y + 36
        scene.items.append(
            Box(
                gx,
                gy,
                group_w,
                group_h,
                [],
                fill=PALETTE["lane"],
                stroke=PALETTE["lane_border"],
                radius=10,
            )
        )
        scene.items.append(
            Text(
                gx + group_w / 2,
                gy + 18,
                name,
                size=10.5,
                bold=True,
                color=PALETTE["muted"],
                anchor="middle",
            )
        )
        for row, (label, sub) in enumerate(items):
            cy = gy + 30 + row * (card_h + gap)
            lines = wrap(label, card_w - 12, 10, 1) + wrap(sub, card_w - 12, 8.5, 1)
            scene.items.append(Box(gx + 12, cy, card_w, card_h, lines, style=style, font_size=9.5))
        centers[name] = (gx + group_w / 2, gy + group_h / 2)
    if left:
        for row, (label, style) in enumerate(left):
            y = boundary_y + 50 + row * 70
            scene.items.append(
                Box(margin, y, side_w, 46, wrap(label, side_w - 12, 10, 2), style=style)
            )
            scene.items.append(Line(points=[(margin + side_w, y + 23), (inner_x, y + 23)]))
    if right:
        rx = inner_x + boundary_w + 30
        for row, (label, sub, style) in enumerate(right):
            y = boundary_y + 50 + row * 70
            scene.items.append(
                Box(
                    rx,
                    y,
                    side_w,
                    46,
                    wrap(label, side_w - 12, 10, 1) + wrap(sub, side_w - 12, 8.5, 1),
                    style=style,
                )
            )
            scene.items.append(
                Line(points=[(inner_x + boundary_w, y + 23), (rx, y + 23)], dashed=row > 0)
            )
    return scene


def flow_scene(title: str, steps: list[str], style: str = "application", columns: int = 3) -> Scene:
    """Numbered steps laid out left-to-right in rows (snake order kept simple: row-major)."""
    card_w, card_h, gap_x, gap_y, margin = 190.0, 54.0, 46.0, 30.0, 20.0
    columns = max(1, min(columns, len(steps) or 1))
    rows = (len(steps) + columns - 1) // columns
    width = margin * 2 + columns * card_w + (columns - 1) * gap_x
    height = margin * 2 + rows * card_h + (rows - 1) * gap_y
    scene = Scene(width=width, height=height, title=title)
    positions = []
    for number, _ in enumerate(steps):
        row, col = divmod(number, columns)
        positions.append((margin + col * (card_w + gap_x), margin + row * (card_h + gap_y)))
    for number in range(len(steps) - 1):
        (x1, y1), (x2, y2) = positions[number], positions[number + 1]
        if y1 == y2:
            scene.items.append(Line(points=[(x1 + card_w, y1 + card_h / 2), (x2, y2 + card_h / 2)]))
        else:
            mid = y1 + card_h + gap_y / 2
            scene.items.append(
                Line(
                    points=[
                        (x1 + card_w / 2, y1 + card_h),
                        (x1 + card_w / 2, mid),
                        (x2 + card_w / 2, mid),
                        (x2 + card_w / 2, y2),
                    ]
                )
            )
    for number, step in enumerate(steps):
        x, y = positions[number]
        scene.items.append(
            Box(
                x,
                y,
                card_w,
                card_h,
                wrap(f"{number + 1}. {step}", card_w - 14, 10, 3),
                style=style,
                font_size=10,
                bold_first=False,
            )
        )
    return scene
