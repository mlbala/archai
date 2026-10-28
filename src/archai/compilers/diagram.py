from __future__ import annotations

import xml.etree.ElementTree as ET

from archai.application.designer import LANES
from archai.compilers.scene import LayoutEdge, LayoutNode, Scene, layered_scene, to_png, to_svg
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
    root = ET.Element("mxfile", {"host": "app.diagrams.net", "agent": "ArchAI"})
    diagram = ET.SubElement(root, "diagram", {"id": "architecture", "name": "Architecture"})
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
    return ET.tostring(root, encoding="unicode", xml_declaration=True) + "\n"


def safe_id(value: str) -> str:
    return "N_" + "".join(character if character.isalnum() else "_" for character in value)
