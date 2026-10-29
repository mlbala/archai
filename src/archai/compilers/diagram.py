from __future__ import annotations

import xml.etree.ElementTree as ET

from archai.application.designer import LANES
from archai.compilers.scene import (
    PALETTE,
    STROKES,
    Box,
    LayoutEdge,
    LayoutNode,
    Line,
    Scene,
    Text,
    layered_scene,
    to_png,
    to_svg,
)
from archai.schemas.models import ArchitectureGraph

NODE_WIDTH = 190
NODE_HEIGHT = 64
LANE_GAP = 70
ROW_GAP = 30
DRAWIO_STYLES = {
    "client": "fillColor=#fef3c7;strokeColor=#b45309;",
    "identity": "fillColor=#fde68a;strokeColor=#b45309;",
    "gateway": "fillColor=#e0e7ff;strokeColor=#4338ca;",
    "policy": "fillColor=#ede9fe;strokeColor=#6d28d9;",
    "ai-gateway": "fillColor=#dcfce7;strokeColor=#15803d;",
    "managed-model": "fillColor=#bbf7d0;strokeColor=#166534;",
    "data": "shape=cylinder3;boundedLbl=1;size=10;fillColor=#fce7f3;strokeColor=#be185d;",
    "queue": "fillColor=#ffe4e6;strokeColor=#be123c;",
    "worker": "fillColor=#fae8ff;strokeColor=#a21caf;",
    "ingestion": "fillColor=#fae8ff;strokeColor=#a21caf;",
    "operations": "fillColor=#e2e8f0;strokeColor=#475569;",
}


def _lane_index(graph: ArchitectureGraph) -> dict[str, int]:
    known = {lane: number for number, lane in enumerate(LANES)}
    extra = [node.lane for node in graph.nodes if node.lane not in known]
    for lane in dict.fromkeys(extra):
        known[lane] = len(known)
    return known


def mermaid(graph: ArchitectureGraph) -> str:
    lines = ["flowchart LR"]
    for node in graph.nodes:
        label = node.label.replace('"', "#quot;")
        lines.append(f'    {safe_id(node.id)}["{label}"]')
    for edge in graph.edges:
        label = edge.label.replace('"', "#quot;").replace("|", "/")
        arrow = "-.->" if edge.kind in {"identity", "telemetry", "fallback"} else "-->"
        lines.append(f'    {safe_id(edge.source)} {arrow}|"{label}"| {safe_id(edge.target)}')
    return "\n".join(lines) + "\n"


def _scene(graph: ArchitectureGraph) -> Scene:
    lanes = _lane_index(graph)
    nodes = [
        LayoutNode(node.id, node.label, None, lanes[node.lane], _style(node.kind))
        for node in graph.nodes
    ]
    edges = [
        LayoutEdge(
            edge.source,
            edge.target,
            edge.label if edge.kind != "telemetry" else None,
            edge.kind in {"identity", "telemetry", "fallback"},
        )
        for edge in graph.edges
    ]
    titles = [lane for lane, _ in sorted(lanes.items(), key=lambda item: item[1])]
    return layered_scene("Architecture", nodes, edges, titles)


def _style(kind: str) -> str:
    return {
        "client": "client",
        "identity": "identity",
        "gateway": "gateway",
        "frontend": "gateway",
        "policy": "policy",
        "ai-gateway": "ai",
        "managed-model": "model",
        "data": "data",
        "queue": "queue",
        "worker": "worker",
        "ingestion": "worker",
        "operations": "ops",
    }.get(kind, "application")


def svg(graph: ArchitectureGraph) -> str:
    return to_svg(_scene(graph))


def png(graph: ArchitectureGraph) -> bytes:
    return to_png(_scene(graph))


def drawio(graph: ArchitectureGraph) -> str:
    return drawio_document([("architecture", "Architecture", graph)])


def drawio_scene(scene: Scene, page_id: str | None = None, name: str | None = None) -> str:
    return drawio_document([(page_id or "scene", name or scene.title, scene)])


def drawio_document(pages: list[tuple[str, str, ArchitectureGraph | Scene]]) -> str:
    root = ET.Element("mxfile", {"host": "app.diagrams.net", "agent": "ArchAI"})
    for page_id, name, source in pages:
        if isinstance(source, ArchitectureGraph):
            root.append(_graph_diagram(page_id, name, source))
        else:
            root.append(_scene_diagram(page_id, name, source))
    return ET.tostring(root, encoding="unicode", xml_declaration=True) + "\n"


def _graph_diagram(page_id: str, name: str, graph: ArchitectureGraph) -> ET.Element:
    diagram = ET.Element("diagram", {"id": page_id, "name": name})
    model = ET.SubElement(
        diagram, "mxGraphModel", {"dx": "1200", "dy": "800", "grid": "1", "page": "0"}
    )
    mxroot = ET.SubElement(model, "root")
    ET.SubElement(mxroot, "mxCell", {"id": "0"})
    ET.SubElement(mxroot, "mxCell", {"id": "1", "parent": "0"})
    lanes = _lane_index(graph)
    counts = dict.fromkeys(lanes, 0)
    lane_width = NODE_WIDTH + LANE_GAP
    max_rows = max(
        (sum(1 for node in graph.nodes if node.lane == lane) for lane in lanes), default=1
    )
    for lane, number in lanes.items():
        if not any(node.lane == lane for node in graph.nodes):
            continue
        cell = ET.SubElement(
            mxroot,
            "mxCell",
            {
                "id": f"lane-{number}",
                "value": lane,
                "style": "swimlane;horizontal=1;startSize=26;fillColor=#f1f5f9;"
                "strokeColor=#cbd5e1;fontStyle=1;html=0;",
                "vertex": "1",
                "parent": "1",
            },
        )
        ET.SubElement(
            cell,
            "mxGeometry",
            {
                "x": str(20 + number * lane_width),
                "y": "20",
                "width": str(NODE_WIDTH + 30),
                "height": str(50 + max_rows * (NODE_HEIGHT + ROW_GAP)),
                "as": "geometry",
            },
        )
    for node in graph.nodes:
        number = lanes[node.lane]
        x = 20 + number * lane_width + 15
        y = 60 + counts[node.lane] * (NODE_HEIGHT + ROW_GAP)
        counts[node.lane] += 1
        cell = ET.SubElement(
            mxroot,
            "mxCell",
            {
                "id": node.id,
                "value": node.label,
                "style": "rounded=1;whiteSpace=wrap;html=0;"
                + DRAWIO_STYLES.get(node.kind, "fillColor=#dbeafe;strokeColor=#1d4ed8;"),
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
        dashed = "dashed=1;" if edge.kind in {"identity", "telemetry", "fallback"} else ""
        cell = ET.SubElement(
            mxroot,
            "mxCell",
            {
                "id": edge.id,
                "value": edge.label,
                "style": f"edgeStyle=orthogonalEdgeStyle;rounded=1;html=0;{dashed}",
                "edge": "1",
                "parent": "1",
                "source": edge.source,
                "target": edge.target,
            },
        )
        ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
    return diagram


def _scene_diagram(page_id: str, name: str, scene: Scene) -> ET.Element:
    diagram = ET.Element("diagram", {"id": page_id, "name": name})
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": str(max(1, int(scene.width))),
            "dy": str(max(1, int(scene.height))),
            "grid": "1",
            "page": "1",
            "pageWidth": str(max(1, int(scene.width))),
            "pageHeight": str(max(1, int(scene.height))),
        },
    )
    mxroot = ET.SubElement(model, "root")
    ET.SubElement(mxroot, "mxCell", {"id": "0"})
    ET.SubElement(mxroot, "mxCell", {"id": "1", "parent": "0"})
    for index, item in enumerate(scene.items):
        if isinstance(item, Box):
            fill = item.fill or PALETTE.get(item.style, PALETTE["application"])
            stroke = item.stroke or STROKES.get(item.style, PALETTE["line"])
            shape = (
                "shape=cylinder3;boundedLbl=1;size=10;" if item.style == "data" else "rounded=1;"
            )
            dash = "dashed=1;" if item.dashed else ""
            cell = ET.SubElement(
                mxroot,
                "mxCell",
                {
                    "id": f"{page_id}-box-{index}",
                    "value": "\n".join(item.lines),
                    "style": f"{shape}whiteSpace=wrap;html=0;fillColor={fill};"
                    f"strokeColor={stroke};{dash}",
                    "vertex": "1",
                    "parent": "1",
                },
            )
            ET.SubElement(
                cell,
                "mxGeometry",
                {
                    "x": str(item.x),
                    "y": str(item.y),
                    "width": str(item.w),
                    "height": str(item.h),
                    "as": "geometry",
                },
            )
        elif isinstance(item, Text):
            align = {"start": "left", "middle": "center", "end": "right"}[item.anchor]
            width = max(40.0, len(item.text) * item.size * 0.6)
            x = item.x if item.anchor == "start" else item.x - width / 2
            if item.anchor == "end":
                x = item.x - width
            cell = ET.SubElement(
                mxroot,
                "mxCell",
                {
                    "id": f"{page_id}-text-{index}",
                    "value": item.text,
                    "style": f"text;html=0;align={align};verticalAlign=middle;"
                    f"fontSize={item.size:.0f};fontColor={item.color};"
                    f"{'fontStyle=1;' if item.bold else ''}",
                    "vertex": "1",
                    "parent": "1",
                },
            )
            ET.SubElement(
                cell,
                "mxGeometry",
                {
                    "x": str(x),
                    "y": str(item.y - item.size),
                    "width": str(width),
                    "height": str(item.size * 1.6),
                    "as": "geometry",
                },
            )
        elif isinstance(item, Line) and item.points:
            style = "html=0;rounded=0;"
            style += "endArrow=classic;" if item.arrow else "endArrow=none;"
            if item.dashed:
                style += "dashed=1;"
            cell = ET.SubElement(
                mxroot,
                "mxCell",
                {
                    "id": f"{page_id}-line-{index}",
                    "style": style,
                    "edge": "1",
                    "parent": "1",
                },
            )
            if item.label:
                cell.set("value", item.label)
            geom = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
            start_x, start_y = item.points[0]
            end_x, end_y = item.points[-1]
            ET.SubElement(
                geom, "mxPoint", {"x": str(start_x), "y": str(start_y), "as": "sourcePoint"}
            )
            ET.SubElement(geom, "mxPoint", {"x": str(end_x), "y": str(end_y), "as": "targetPoint"})
            if len(item.points) > 2:
                array = ET.SubElement(geom, "Array", {"as": "points"})
                for point_x, point_y in item.points[1:-1]:
                    ET.SubElement(array, "mxPoint", {"x": str(point_x), "y": str(point_y)})
    return diagram


def safe_id(value: str) -> str:
    return "N_" + "".join(character if character.isalnum() else "_" for character in value)
