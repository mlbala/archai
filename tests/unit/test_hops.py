from __future__ import annotations

from pathlib import Path

import yaml

from archai.application import service
from archai.compilers.hops import (
    control_ownership,
    other_paths,
    primary_api,
    request_hops,
    trust_boundaries,
)

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
    assert any(walk.key.startswith("workflow-") for walk in other_paths(design))
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
