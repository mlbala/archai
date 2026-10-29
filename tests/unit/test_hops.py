from __future__ import annotations

from pathlib import Path

import yaml

from archai.application import service
from archai.application.designer import build_graph
from archai.compilers.hld import high_level_design_document
from archai.compilers.hops import (
    control_ownership,
    other_paths,
    primary_api,
    request_hops,
    trust_boundaries,
)
from archai.compilers.lld import low_level_design_document
from archai.compilers.master import master_design_document

REQUIREMENTS = Path("examples/azure-enterprise-rag/requirements.yaml")


def _design(tmp_path: Path, source: Path = REQUIREMENTS, project: str = "hops"):
    store, revision = service.run_generation(
        project=project,
        scope=service.auto_scope(),
        output_dir=tmp_path,
        files=[source],
        idea=None,
        stdin_enabled=False,
        answers=None,
        profile=None,
        region=None,
        target_providers=None,
        topology=None,
        archetypes=[],
        allow_assumptions=False,
        offline=True,
    )
    return store.load_design(revision)


def test_request_hops_follow_primary_chat_contract(tmp_path):
    design = _design(tmp_path)
    api = primary_api(design)
    assert api is not None
    assert api.path == "/v1/chat"
    hops = request_hops(design)
    actions = [hop.action for hop in hops]
    assert f"{api.method} {api.path} with {api.auth}" in actions
    assert "POST /v1/chat with bearer token" not in actions
    chat = next(hop for hop in hops if api.path in hop.action)
    assert chat.interface == f"`{api.method} {api.path}`, streaming"
    assert "conversation_id" in chat.payload
    assert chat.owner.startswith("Enterprise API gateway") or "(`svc-" in chat.owner
    assert any("PKCE" in hop.action or "authorization code" in hop.action for hop in hops)
    assert any("svc-" in hop.owner for hop in hops)
    walks = {walk.key: walk for walk in other_paths(design)}
    assert "oauth-user" in walks
    assert walks["oauth-user"].hops
    assert "workflow-interactive" not in walks
    assert any(key.startswith("workflow-") for key in walks)
    labels = {label for label, _owner, _bound in trust_boundaries(design)}
    assert "Authentication and request limits" in labels
    assert "Cache authorization" in labels
    ownership = control_ownership(design)
    assert ownership["authentication"] == "enterprise-api-gateway"
    assert ownership["cache_authorization"] == "application"
    assert "hld" not in design.components
    assert "lld" not in design.components


def test_excluded_identity_and_cache_drop_those_hops(tmp_path):
    requested = yaml.safe_load(REQUIREMENTS.read_text())
    requested["excluded_components"] = ["cache", "RBAC", "cloud deployment"]
    source = tmp_path / "excluded.yaml"
    source.write_text(yaml.safe_dump(requested))
    design = _design(tmp_path / "excluded", source, "excluded")
    assert design.identity_policy is None
    assert design.cache_policy is None
    hops = request_hops(design)
    assert not any("Sign in" in hop.action or "PKCE" in hop.action for hop in hops)
    assert not any(walk.key.startswith("oauth-") for walk in other_paths(design))
    labels = {label for label, _owner, _bound in trust_boundaries(design)}
    assert "Authentication and request limits" not in labels
    assert "Cache authorization" not in labels
    ownership = control_ownership(design)
    assert "authentication" not in ownership
    assert "cache_authorization" not in ownership


def test_faq_omits_jobs_worker_and_async_path(tmp_path):
    requested = {
        "idea": "Internal FAQ chatbot that answers from a policy handbook.",
        "business_outcome": "Let employees find policy answers without a ticket.",
        "users": ["Employees"],
        "archetypes": ["enterprise-rag"],
        "region": "westeurope",
        "data_residency": ["westeurope"],
        "tenant_isolation": "single",
        "allowed_target_providers": ["Azure OpenAI"],
        "tool_side_effects": "forbidden",
        "avg_rps": 1,
        "peak_rps": 3,
        "input_tokens": 800,
        "output_tokens": 200,
        "model_calls_per_request": 1,
        "monthly_budget": 2000,
        "availability_target": 99.5,
        "currency": "EUR",
        "profile": "azure-aca",
        "topology": "single-cloud",
        "client_channels": ["web"],
        "excluded_components": ["cache"],
    }
    source = tmp_path / "faq.yaml"
    source.write_text(yaml.safe_dump(requested))
    design = _design(tmp_path / "faq", source, "faq")
    kinds = {service.kind for service in design.services}
    paths = {contract.path for contract in design.api_contracts}
    assert "worker" not in kinds
    assert "tool-executor" not in kinds
    assert "ingestion" in kinds
    assert "/v1/jobs" not in paths
    assert "/v1/chat" in paths
    assert design.identity_policy is None
    assert design.components["auth"].status.value == "not_applicable"
    assert design.cache_policy is None
    assert not any(walk.key == "async" for walk in other_paths(design))
    assert not any(walk.key.startswith("oauth-") for walk in other_paths(design))
    assert not any(service.id == "svc-worker" for service in design.services)
    graph = build_graph(design)
    high = high_level_design_document(design, graph, [])
    assert "Identity: not in scope" in high
    assert "Entra ID" not in high
    assert "['westeurope']" not in high
    assert "Region and residency: westeurope; westeurope" in high
    assert "tool approval" not in high
    low = low_level_design_document(design, graph, [])
    assert "<!-- archai:diagram architecture -->" not in low
    assert "<!-- archai:diagram request -->" in low
    assert "<!-- archai:diagram oauth-user -->" not in low
    assert "Interactive managed-model request" not in low
    assert "#### Step 1 —" not in low
    master = master_design_document(design, [])
    assert "Asynchronous outbox" not in master
    assert "before a tool or model call" not in master
    assert "before fallback traffic is enabled" not in master
    assert "Index new source documents with access controls so answers stay current." in master
    assert "Check answers for policy and sensitive data before they are shown." in master
    assert "Evaluate the primary chat route before production traffic." in master
    assert "Budget, guardrails, and the threat model are in place before broader rollout." in master


def test_batch_primary_api_is_jobs(tmp_path):
    requested = yaml.safe_load(REQUIREMENTS.read_text())
    requested["idea"] = "Nightly pandas calculations over warehouse extracts. No user interaction."
    requested["business_outcome"] = "Refresh planning figures before the business day."
    requested["users"] = ["scheduler"]
    requested["archetypes"] = ["classification-extraction"]
    source = tmp_path / "batch.yaml"
    source.write_text(yaml.safe_dump(requested))
    design = _design(tmp_path / "batch", source, "batch")
    api = primary_api(design)
    assert api is not None
    assert api.path == "/v1/jobs"
    actions = [hop.action for hop in request_hops(design)]
    assert f"{api.method} {api.path} with {api.auth}" in actions
    assert not any("/v1/chat" in action for action in actions)
    if design.queue_policy:
        async_walk = next(walk for walk in other_paths(design) if walk.key == "async")
        assert any("/v1/jobs" in hop.action for hop in async_walk.hops)
