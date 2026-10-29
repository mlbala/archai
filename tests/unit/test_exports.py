from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

from archai.application import service
from archai.application.designer import build_graph
from archai.compilers.export import export_revision, litellm_yaml, normalize_formats
from archai.compilers.master import master_design_document
from archai.compilers.report import complete_document, component_document
from archai.compilers.scene import to_png, to_svg
from archai.compilers.terraform import apim_policy_xml, compile_infrastructure
from archai.compilers.views import all_views
from archai.domain.scale import minimum_replicas, replica_ceiling, scale_targets

REQUIREMENTS = Path("examples/azure-enterprise-rag/requirements.yaml")


def design_for(tmp_path: Path, profile: str | None = None, source: Path = REQUIREMENTS):
    store, revision = service.run_generation(
        project=f"exp-{profile or 'default'}",
        scope=service.auto_scope(),
        output_dir=tmp_path,
        files=[source],
        idea=None,
        stdin_enabled=False,
        answers=None,
        profile=profile,
        region=None,
        target_providers=None,
        topology=None,
        archetypes=[],
        allow_assumptions=False,
        offline=True,
    )
    return store, revision, store.load_design(revision)


def test_litellm_uses_provider_prefixes_and_fallback_groups(tmp_path):
    _, _, design = design_for(tmp_path)
    config = yaml.safe_load(litellm_yaml(design))
    names = [entry["model_name"] for entry in config["model_list"]]
    assert "enterprise-chat" in names and "enterprise-chat-fallback-1" in names
    models = {
        entry["model_name"]: entry["litellm_params"]["model"] for entry in config["model_list"]
    }
    assert models["enterprise-chat"].startswith("azure/")
    assert models["enterprise-chat-fallback-1"].startswith("bedrock/")
    assert config["router_settings"]["fallbacks"] == [
        {"enterprise-chat": ["enterprise-chat-fallback-1"]}
    ]
    assert not any("fallback" in name for name in names if name.startswith("enterprise-embedding"))
    for entry in config["model_list"]:
        for key, value in entry["litellm_params"].items():
            if "key" in key or "api_base" in key:
                assert str(value).startswith("os.environ/")


def _terraform_consistency(files: dict[str, str]) -> None:
    code = "\n".join(text for path, text in files.items() if path.endswith(".tf"))
    assert code.count("{") == code.count("}")
    declared_vars = set(re.findall(r'variable "([a-z_]+)"', code))
    used_vars = set(re.findall(r"\bvar\.([a-z_]+)", code))
    assert used_vars <= declared_vars, used_vars - declared_vars
    resources = set(re.findall(r'resource "([a-z0-9_]+)" "([a-z0-9_]+)"', code))
    data = set(re.findall(r'data "([a-z0-9_]+)" "([a-z0-9_]+)"', code))
    for kind, name in re.findall(
        r"(?<![.\w])((?:azurerm|aws|random)_[a-z0-9_]+)\.([a-z0-9_]+)\b", code
    ):
        if name in {"id", "name", "arn", "json"}:
            continue
        assert (kind, name) in resources, f"{kind}.{name} is not declared"
    for kind, name in re.findall(r"\bdata\.([a-z0-9_]+)\.([a-z0-9_]+)\b", code):
        assert (kind, name) in data, f"data.{kind}.{name} is not declared"
    literal_secrets = re.findall(r'(?i)\b\w*(password|secret|api_key)\w*\s*=\s*"[^"]+"', code)
    assert not literal_secrets
    assert "apply" not in code.split("#")[0]


@pytest.mark.parametrize("profile", ["azure-aca", "azure-aks", "aws-eks"])
def test_terraform_roots_are_self_consistent_and_secret_free(tmp_path, profile):
    _, _, design = design_for(tmp_path, profile)
    files = compile_infrastructure(design)
    assert "infrastructure/primary/main.tf" in files
    _terraform_consistency(files)
    assert "service_images" in files["infrastructure/primary/variables.tf"] or profile == "aws-eks"
    if profile != "azure-aca":
        manifests = [path for path in files if path.startswith("workloads/kubernetes/")]
        assert manifests
        documents = [
            doc
            for path in manifests
            if path.endswith(".yaml")
            for doc in yaml.safe_load_all(files[path])
        ]
        kinds = {doc["kind"] for doc in documents}
        assert {"Deployment", "ScaledObject", "HorizontalPodAutoscaler"} <= kinds


def test_agnostic_profile_has_no_terraform(tmp_path):
    _, _, design = design_for(tmp_path, "agnostic")
    assert compile_infrastructure(design) == {}


def test_apim_policy_and_views_are_valid_and_renderable(tmp_path):
    _, _, design = design_for(tmp_path)
    ET.fromstring(apim_policy_xml(design))
    graph = build_graph(design)
    views = all_views(design, graph)
    keys = {view.key for view in views}
    assert {
        "architecture",
        "request",
        "oauth-user",
        "oauth-service",
        "deployment",
        "budget",
        "scale",
    } <= keys
    for view in views:
        ET.fromstring(to_svg(view.scene))
        assert view.mermaid.split("\n", 1)[0] in {
            "flowchart LR",
            "sequenceDiagram",
            "stateDiagram-v2",
        }
    assert to_png(views[0].scene).startswith(b"\x89PNG")


def test_documents_are_substantive(tmp_path):
    _, _, design = design_for(tmp_path)
    graph = build_graph(design)
    identity = component_document("auth", design, graph, [])
    assert "authorization_code_pkce" in identity and "client_credentials" in identity
    assert "Roles and permissions" in identity
    system = component_document("system", design, graph, [])
    assert "Microservice catalog" in system and "```mermaid" in system
    assert "Scale-up architecture" in system
    security = component_document("security", design, graph, [])
    assert "LLM01:2025" in security
    complete = complete_document(design, graph, [])
    assert "Requirements traceability" in complete
    assert "Executive summary" in complete
    assert "Microservices" in complete
    assert "## " in complete and "Scale-up architecture" in complete
    assert complete.count("<!-- archai:diagram architecture -->") == 1
    assert complete.count("<!-- archai:diagram scale -->") == 1
    infra = component_document("infra", design, graph, [])
    assert "Scale-up architecture" in infra and "Cloud resources" in infra


def test_component_export_is_scoped(tmp_path):
    store, revision, _ = design_for(tmp_path)
    bundle, manifest = export_revision(store, revision, normalize_formats("core"), ["guard"])
    paths = {item.path for item in manifest.artifacts}
    assert "documents/Guardrails_Design.md" in paths
    assert "policies/guardrails.yaml" in paths
    assert "Complete_AI_System_Design.md" not in paths
    assert "master_design/Master_Design.pdf" not in paths
    assert "litellm.yaml" not in paths
    assert not any(path.startswith("infrastructure/") for path in paths)
    assert (bundle / "diagrams/guardrails.mmd").exists()


def test_scale_plan_matches_generated_autoscalers(tmp_path):
    _, _, design = design_for(tmp_path)
    ceiling = replica_ceiling(design)
    targets = {item.service_id: item for item in scale_targets(design)}
    assert targets["svc-app"].replicas == f"1-{ceiling}"
    assert targets["svc-app"].mode == "http"
    assert "Container Apps" in targets["svc-app"].trigger
    assert targets["svc-worker"].replicas == f"0-{ceiling}"
    assert targets["svc-worker"].mode == "queue"
    assert targets["svc-ingress"].replicas == "managed"
    assert minimum_replicas(design, "application") == 1
    main = compile_infrastructure(design)["infrastructure/primary/main.tf"]
    assert "min_replicas = 1" in main
    assert "min_replicas = 0" in main
    assert f"max_replicas = {ceiling}" in main

    _, _, aks = design_for(tmp_path / "aks", "azure-aks")
    assert minimum_replicas(aks, "application") == 2
    manifests = "\n".join(
        text
        for path, text in compile_infrastructure(aks).items()
        if path.startswith("workloads/kubernetes/") and path.endswith(".yaml")
    )
    assert "minReplicas: 2" in manifests
    assert f"maxReplicas: {replica_ceiling(aks)}" in manifests
    assert "minReplicaCount: 0" in manifests
    worker = next(item for item in scale_targets(aks) if item.service_id == "svc-worker")
    assert worker.trigger.startswith("KEDA")
    assert worker.replicas == f"0-{replica_ceiling(aks)}"


def test_full_pdf_export(tmp_path):
    store, revision, _ = design_for(tmp_path)
    bundle, manifest = export_revision(
        store, revision, normalize_formats("pdf,md"), [*service.auto_scope()]
    )
    pdfs = [item.path for item in manifest.artifacts if item.path.endswith(".pdf")]
    assert "Complete_AI_System_Design.pdf" in pdfs
    assert "master_design/Master_Design.pdf" in pdfs
    assert len(pdfs) >= 15
    assert not [item for item in manifest.artifacts if item.status == "failed"]
    assert (bundle / "Complete_AI_System_Design.pdf").stat().st_size > 50_000
    master_pdf = bundle / "master_design" / "Master_Design.pdf"
    assert master_pdf.read_bytes().startswith(b"%PDF")
    assert master_pdf.stat().st_size > 5_000


def test_optional_components_are_removed_when_excluded(tmp_path):
    requested = yaml.safe_load(REQUIREMENTS.read_text())
    requested["excluded_components"] = ["cache", "RBAC", "cloud deployment"]
    source = tmp_path / "excluded.yaml"
    source.write_text(yaml.safe_dump(requested))
    _, _, design = design_for(tmp_path, source=source)
    assert design.components["cache"].status.value == "not_applicable"
    assert design.cache_policy is None
    assert design.components["auth"].status.value == "not_applicable"
    assert design.identity_policy is None
    assert design.components["infra"].status.value == "not_applicable"
    assert design.deployment is None
    assert design.components["system"].status.value == "valid"
    assert design.services

    batch = dict(requested)
    batch.pop("excluded_components")
    batch["idea"] = "Nightly pandas calculations over warehouse extracts. No user interaction."
    batch["business_outcome"] = "Refresh planning figures before the business day."
    batch["users"] = ["scheduler"]
    batch["archetypes"] = ["classification-extraction"]
    batch_path = tmp_path / "batch.yaml"
    batch_path.write_text(yaml.safe_dump(batch))
    _, _, quiet = design_for(tmp_path / "batch", source=batch_path)
    assert quiet.components["cache"].status.value == "not_applicable"
    assert quiet.components["auth"].status.value == "not_applicable"
    assert quiet.components["infra"].status.value == "valid"
    assert quiet.deployment is not None


def test_master_design_lists_features_plan_and_sprints(tmp_path):
    _, _, design = design_for(tmp_path)
    document = master_design_document(design, [])
    assert "# Master Design" in document
    assert "## 1. Feature catalog" in document
    assert "## 2. Development plan" in document
    assert "## 3. Sprints" in document
    assert "Sprint 1 — Foundation" in document
    assert "Sprint 2 — Core path" in document
    assert "not deployed" in document
    assert "F-01" in document
