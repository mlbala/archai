import xml.etree.ElementTree as ET

import pytest

from archai.compilers.diagram import drawio, svg
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
