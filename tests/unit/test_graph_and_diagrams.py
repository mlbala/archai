import pytest

from archai.compilers.diagram import mermaid, safe_id
from archai.schemas.models import ArchitectureGraph, Edge, Node


def test_graph_rejects_orphan_edges():
    with pytest.raises(ValueError):
        ArchitectureGraph(
            nodes=[Node(id="a", label="A", kind="x", lane="one")],
            edges=[Edge(id="e", source="a", target="b", label="bad")],
        )


def test_mermaid_escapes_labels_and_ids():
    graph = ArchitectureGraph(
        nodes=[Node(id="a-b", label='A "B"', kind="x", lane="one")],
        edges=[Edge(id="e", source="a-b", target="a-b", label="reads|writes", kind="call")],
    )
    text = mermaid(graph)
    assert text.startswith("flowchart LR")
    assert 'N_a_b["A #quot;B#quot;"]' in text
    assert 'N_a_b -->|"reads/writes"| N_a_b' in text
    assert safe_id("svc-app") == "N_svc_app"
