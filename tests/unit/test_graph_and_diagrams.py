import xml.etree.ElementTree as ET

import pytest

from archai.compilers.diagram import drawio, drawio_scene, svg
from archai.compilers.scene import Box, Scene
from archai.schemas.models import ArchitectureGraph, Edge, Node


def test_graph_rejects_orphan_edges():
    with pytest.raises(ValueError):
        ArchitectureGraph(
            nodes=[Node(id="a", label="A", kind="x", lane="one")],
            edges=[Edge(id="e", source="a", target="b", label="bad")],
        )


def test_xml_outputs_parse_and_escape():
    graph = ArchitectureGraph(nodes=[Node(id="a", label="A & B", kind="x", lane="one")], edges=[])
    ET.fromstring(drawio(graph))
    ET.fromstring(svg(graph))
    scene = Scene(
        200,
        80,
        "Step",
        [Box(10, 10, 80, 40, ["Gateway"], style="gateway")],
    )
    ET.fromstring(drawio_scene(scene, "request", "Request path"))
