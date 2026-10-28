from __future__ import annotations

import html
import io
import xml.etree.ElementTree as ET

from archai.schemas.models import ArchitectureGraph

LANE_WIDTH = 260
NODE_WIDTH = 210
NODE_HEIGHT = 64
ROW_HEIGHT = 100


def mermaid(graph: ArchitectureGraph) -> str:
    lines = ["flowchart LR"]
    for node in graph.nodes:
        label = node.label.replace('"', "'")
        lines.append(f'    {safe_id(node.id)}["{label}"]')
    for edge in graph.edges:
        label = edge.label.replace('"', "'")
        arrow = "-.->" if edge.kind in {"identity", "telemetry"} else "-->"
        lines.append(f'    {safe_id(edge.source)} {arrow}|"{label}"| {safe_id(edge.target)}')
    return "\n".join(lines) + "\n"


def svg(graph: ArchitectureGraph) -> str:
    lanes = list(dict.fromkeys(node.lane for node in graph.nodes))
    lane_index = {lane: index for index, lane in enumerate(lanes)}
    positions: dict[str, tuple[int, int]] = {}
    counts: dict[str, int] = {lane: 0 for lane in lanes}
    for node in graph.nodes:
        x = 30 + lane_index[node.lane] * LANE_WIDTH
        y = 70 + counts[node.lane] * ROW_HEIGHT
        counts[node.lane] += 1
        positions[node.id] = (x, y)
    width = max(500, 60 + len(lanes) * LANE_WIDTH)
    height = max(300, 120 + max(counts.values(), default=1) * ROW_HEIGHT)
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<defs><marker id="arrow" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#52606d"/></marker></defs>',
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
    ]
    for lane, index in lane_index.items():
        x = 20 + index * LANE_WIDTH
        lines.append(
            f'<text x="{x + 10}" y="28" font-family="sans-serif" font-size="13" font-weight="bold" fill="#334155">{html.escape(lane)}</text>'
        )
    for edge in graph.edges:
        x1, y1 = positions[edge.source]
        x2, y2 = positions[edge.target]
        lines.append(
            f'<path d="M {x1 + NODE_WIDTH} {y1 + NODE_HEIGHT / 2} L {x2} {y2 + NODE_HEIGHT / 2}" stroke="#52606d" fill="none" marker-end="url(#arrow)"/>'
        )
    for node in graph.nodes:
        x, y = positions[node.id]
        lines.append(
            f'<rect id="{html.escape(node.id)}" x="{x}" y="{y}" width="{NODE_WIDTH}" height="{NODE_HEIGHT}" rx="8" fill="#e0f2fe" stroke="#0369a1"/>'
        )
        label = html.escape(node.label[:30])
        lines.append(
            f'<text x="{x + 10}" y="{y + 36}" font-family="sans-serif" font-size="13" fill="#0f172a">{label}</text>'
        )
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def drawio(graph: ArchitectureGraph) -> str:
    root = ET.Element("mxfile", {"host": "app.diagrams.net"})
    diagram = ET.SubElement(root, "diagram", {"id": "architecture", "name": "Architecture"})
    model = ET.SubElement(diagram, "mxGraphModel", {"dx": "1000", "dy": "700", "grid": "1"})
    mxroot = ET.SubElement(model, "root")
    ET.SubElement(mxroot, "mxCell", {"id": "0"})
    ET.SubElement(mxroot, "mxCell", {"id": "1", "parent": "0"})
    lanes = list(dict.fromkeys(node.lane for node in graph.nodes))
    counts = {lane: 0 for lane in lanes}
    for node in graph.nodes:
        x = 30 + lanes.index(node.lane) * LANE_WIDTH
        y = 50 + counts[node.lane] * ROW_HEIGHT
        counts[node.lane] += 1
        cell = ET.SubElement(
            mxroot,
            "mxCell",
            {
                "id": node.id,
                "value": node.label,
                "style": "rounded=1;whiteSpace=wrap;html=0;",
                "vertex": "1",
                "parent": "1",
            },
        )
        ET.SubElement(
            cell,
            "mxGeometry",
            {
                "x": str(x),
                "y": str(y),
                "width": str(NODE_WIDTH),
                "height": str(NODE_HEIGHT),
                "as": "geometry",
            },
        )
    for edge in graph.edges:
        cell = ET.SubElement(
            mxroot,
            "mxCell",
            {
                "id": edge.id,
                "value": edge.label,
                "style": "edgeStyle=orthogonalEdgeStyle;html=0;",
                "edge": "1",
                "parent": "1",
                "source": edge.source,
                "target": edge.target,
            },
        )
        ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
    return ET.tostring(root, encoding="unicode", xml_declaration=True) + "\n"


def png(graph: ArchitectureGraph) -> bytes:
    """Render the same deterministic lane layout with the optional Pillow backend."""
    from PIL import Image, ImageDraw

    lanes = list(dict.fromkeys(node.lane for node in graph.nodes))
    lane_index = {lane: index for index, lane in enumerate(lanes)}
    counts: dict[str, int] = {lane: 0 for lane in lanes}
    positions: dict[str, tuple[int, int]] = {}
    for node in graph.nodes:
        positions[node.id] = (
            30 + lane_index[node.lane] * LANE_WIDTH,
            70 + counts[node.lane] * ROW_HEIGHT,
        )
        counts[node.lane] += 1
    width = max(500, 60 + len(lanes) * LANE_WIDTH)
    height = max(300, 120 + max(counts.values(), default=1) * ROW_HEIGHT)
    image = Image.new("RGB", (width, height), "#f8fafc")
    drawing = ImageDraw.Draw(image)
    for lane, index in lane_index.items():
        drawing.text((30 + index * LANE_WIDTH, 18), lane, fill="#334155")
    for edge in graph.edges:
        x1, y1 = positions[edge.source]
        x2, y2 = positions[edge.target]
        drawing.line(
            (x1 + NODE_WIDTH, y1 + NODE_HEIGHT // 2, x2, y2 + NODE_HEIGHT // 2),
            fill="#52606d",
            width=2,
        )
    for node in graph.nodes:
        x, y = positions[node.id]
        drawing.rounded_rectangle(
            (x, y, x + NODE_WIDTH, y + NODE_HEIGHT),
            radius=8,
            fill="#e0f2fe",
            outline="#0369a1",
            width=2,
        )
        drawing.text((x + 10, y + 24), node.label[:30], fill="#0f172a")
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False)
    return output.getvalue()


def safe_id(value: str) -> str:
    return "N_" + "".join(character if character.isalnum() else "_" for character in value)
