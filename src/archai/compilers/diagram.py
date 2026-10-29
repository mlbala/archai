"""Compile an architecture graph to Mermaid. SVG, PNG, and draw.io are not generated."""

from __future__ import annotations

from archai.schemas.models import ArchitectureGraph


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


def safe_id(value: str) -> str:
    return "N_" + "".join(character if character.isalnum() else "_" for character in value)
