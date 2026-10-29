from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from archai.application.registry import AUTO_COMPONENTS, COMPONENTS, DOCUMENT_PACKAGES
from archai.compilers.diagram import drawio, drawio_document, drawio_scene
from archai.compilers.hld import high_level_design_document, high_level_views
from archai.compilers.hops import control_ownership
from archai.compilers.lld import low_level_design_document, low_level_views
from archai.compilers.master import master_design_document
from archai.compilers.report import (
    component_document,
    diagram_document,
    document_name,
    project_complete,
    requirements_document,
    source_label,
)
from archai.compilers.scene import Scene, to_png, to_svg
from archai.compilers.terraform import apim_policy_xml, compile_infrastructure
from archai.compilers.views import View, all_views, views_for
from archai.ingestion import sha256_bytes
from archai.persistence.store import ProjectStore, json_bytes, new_bundle_id
from archai.schemas.models import (
    ArchitectureGraph,
    ArtifactRecord,
    EnterpriseDesign,
    ExportBundleManifest,
)

CORE_FORMATS = {"md", "json", "yaml", "mmd", "drawio", "svg", "tf", "xml"}
ALL_FORMATS = CORE_FORMATS | {"png", "pdf"}
REVIEW_FILES = {
    "hld": "documents/High_Level_Design",
    "lld": "documents/Low_Level_Design",
    "master": "documents/Master_Design",
}
DIAGRAM_VIEWS = (
    "system",
    "context",
    "deployment",
    "request",
    "ingestion",
    "guardrails",
    "workflow",
    "fallback",
    "budget",
    "recovery",
    "oauth",
    "data",
    "async",
    "scale",
    "scaleup",
)
VIEW_ALIASES = {
    "system": "architecture",
    "workflow": "workflow-",
    "oauth": "oauth-",
    "scaleup": "scale",
}


def normalize_formats(value: str) -> set[str]:
    if value == "core":
        return set(CORE_FORMATS)
    if value == "all":
        return set(ALL_FORMATS)
    formats = {item.strip().lower() for item in value.split(",") if item.strip()}
    unknown = formats - ALL_FORMATS
    if unknown:
        raise ValueError(f"unknown formats: {', '.join(sorted(unknown))}")
    return formats


def select_views(views: list[View], scope: list[str], view: str | None) -> list[View]:
    if view:
        key = VIEW_ALIASES.get(view, view)
        return [
            item
            for item in views
            if item.key == key or (key.endswith("-") and item.key.startswith(key))
        ]
    if "doc" in scope or "diagram" in scope or "lld" in scope or set(AUTO_COMPONENTS) <= set(scope):
        return views
    selected: list[View] = []
    for component in scope:
        for item in views_for(component, views):
            if item not in selected:
                selected.append(item)
    return selected


def export_revision(
    store: ProjectStore,
    revision: int,
    formats: set[str],
    scope: list[str] | None = None,
    view: str | None = None,
) -> tuple[Path, ExportBundleManifest]:
    design = store.load_design(revision)
    graph = store.load_graph(revision)
    revision_manifest = store.load_manifest(revision)
    selected_scope = scope or revision_manifest.selected_scope
    full = "doc" in selected_scope
    package_only = (not full) and set(selected_scope) <= set(DOCUMENT_PACKAGES)
    write_hld = full or "hld" in selected_scope
    write_lld = full or "lld" in selected_scope
    diagnostics = revision_manifest.diagnostics
    bundle_id = new_bundle_id()
    root = store.root
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    artifacts: list[ArtifactRecord] = []

    def write(relative: str, content: str | bytes) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode() if isinstance(content, str) else content
        path.write_bytes(data)
        artifacts.append(
            ArtifactRecord(path=relative, sha256=sha256_bytes(data), status="generated")
        )

    def record(relative: str, status: str, reason: str) -> None:
        artifacts.append(ArtifactRecord(path=relative, sha256=None, status=status, reason=reason))

    def covers(*components: str) -> bool:
        return full or any(name in selected_scope for name in components)

    def write_png(relative: str, scene: Scene) -> None:
        try:
            write(relative, to_png(scene))
        except (ImportError, OSError) as exc:
            record(relative, "failed", f"optional Pillow renderer unavailable: {exc}")

    views = all_views(design, graph)
    selected_views = select_views(views, selected_scope, view)
    skip_component_docs = {"doc", "requirements", *DOCUMENT_PACKAGES}
    documents: dict[str, str] = {}
    if covers("requirements"):
        documents["AI_Enterprise_PRD.md"] = requirements_document(design)
    for component in selected_scope:
        if component in skip_component_docs or component not in COMPONENTS:
            continue
        if component not in design.components and component != "diagram":
            continue
        documents[document_name(component)] = (
            diagram_document(design, graph)
            if component == "diagram"
            else component_document(component, design, graph, diagnostics, views=views)
        )
    if full:
        for component in COMPONENTS:
            if component in skip_component_docs | {"diagram"} or component in selected_scope:
                continue
            if component in design.components:
                documents[document_name(component)] = component_document(
                    component, design, graph, diagnostics, views=views
                )

    hld_markdown = high_level_design_document(design, graph, diagnostics) if write_hld else None
    lld_markdown = low_level_design_document(design, graph, diagnostics) if write_lld else None
    master_markdown = master_design_document(design, diagnostics) if full else None

    if "json" in formats:
        write("state/enterprise_design.json", json_bytes(design))
        write("state/architecture_graph.json", json_bytes(graph))
        write(
            "state/validation_report.json",
            json_bytes(
                {
                    "scope": selected_scope,
                    "scope_valid": revision_manifest.scope_valid,
                    "project_complete": revision_manifest.project_complete,
                    "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
                    "verification": [item.model_dump(mode="json") for item in design.verification],
                }
            ),
        )
        if covers("api", "routing") and (design.model_aliases or design.api_contracts):
            write("config/gateway/api_gateway_and_routing_config.json", _gateway_json(design))
        if covers("cost") and (design.costs or design.capacity):
            write(
                "state/capacity_and_cost.json",
                json_bytes(
                    {
                        "capacity": design.capacity.model_dump(mode="json")
                        if design.capacity
                        else None,
                        "estimates": [item.model_dump(mode="json") for item in design.costs],
                        "note": "Scenario estimates from supplied inputs; not live quotations.",
                    }
                ),
            )
        if covers("infra") and design.deployment:
            write(
                "state/cloud_bom.json",
                json_bytes(
                    {
                        "profile": design.deployment.model_dump(mode="json"),
                        "validation_level": "generated design only",
                    }
                ),
            )
    if "md" in formats:
        for name, content in sorted(documents.items()):
            write(f"{_markdown_folder(name)}/{name}", content)
        if hld_markdown is not None:
            write(f"{REVIEW_FILES['hld']}.md", hld_markdown)
        if lld_markdown is not None:
            write(f"{REVIEW_FILES['lld']}.md", lld_markdown)
        if master_markdown is not None:
            write(f"{REVIEW_FILES['master']}.md", master_markdown)
        if covers("api", "budget", "guard", "auth", "routing"):
            write("config/integration_contracts.md", _integration_contracts(design))
    if "yaml" in formats:
        if covers("routing") and design.model_aliases:
            write("config/gateway/litellm.yaml", litellm_yaml(design))
        for name, (component, value) in _policy_files(design).items():
            if covers(component):
                write(f"config/policies/{name}", yaml.safe_dump(value, sort_keys=True))
    if "xml" in formats and covers("api"):
        if design.requirements.profile.startswith("azure"):
            xml = apim_policy_xml(design)
            ET.fromstring(xml)
            write("config/gateway/apim_policies.xml", xml)
        else:
            record(
                "config/gateway/apim_policies.xml",
                "not_applicable",
                "APIM is not selected for this profile",
            )
    shared_diagrams = selected_views if not package_only else []
    svg_sources = {item.key: to_svg(item.scene) for item in shared_diagrams}
    if "mmd" in formats:
        for item in shared_diagrams:
            write(f"diagrams/mermaid/{item.key}.mmd", item.mermaid)
    if "svg" in formats:
        for key, source in svg_sources.items():
            ET.fromstring(source)
            write(f"diagrams/svg/{key}.svg", source)
    if "drawio" in formats:
        for item in shared_diagrams:
            source = (
                drawio(graph)
                if item.key == "architecture"
                else drawio_scene(item.scene, item.key, item.title)
            )
            ET.fromstring(source)
            write(f"diagrams/drawio/{item.key}.drawio", source)
    if "tf" in formats and covers("infra") and design.deployment:
        if design.requirements.profile == "agnostic":
            record(
                "infrastructure/primary/main.tf",
                "not_applicable",
                "agnostic profile has no fake universal Terraform",
            )
        else:
            for relative, content in sorted(compile_infrastructure(design).items()):
                write(relative, content)
    if "png" in formats:
        for item in shared_diagrams:
            write_png(f"diagrams/png/{item.key}.png", item.scene)
    if write_hld:
        _write_package_diagrams(
            write,
            write_png,
            formats,
            "hld",
            high_level_views(design, graph),
            graph,
            package_only,
        )
    if write_lld:
        _write_package_diagrams(
            write,
            write_png,
            formats,
            "lld",
            low_level_views(design, graph),
            graph,
            package_only,
        )
    if "pdf" in formats:
        scenes = {item.key: item.scene for item in views}
        pdf_jobs: list[tuple[str, str, str]] = []
        for name, content in sorted(documents.items()):
            title = content.splitlines()[0].lstrip("# ").strip() if content else name
            pdf_jobs.append(
                (f"{_markdown_folder(name)}/{name.removesuffix('.md')}.pdf", content, title)
            )
        if hld_markdown is not None:
            pdf_jobs.append((f"{REVIEW_FILES['hld']}.pdf", hld_markdown, "High-Level Design"))
        if lld_markdown is not None:
            pdf_jobs.append((f"{REVIEW_FILES['lld']}.pdf", lld_markdown, "Low-Level Design"))
        if master_markdown is not None:
            pdf_jobs.append((f"{REVIEW_FILES['master']}.pdf", master_markdown, "Master Design"))
        for relative, content, title in pdf_jobs:
            try:
                _pdf(root / relative, content, title, design, scenes)
            except ImportError as exc:
                record(relative, "failed", f"optional ReportLab renderer unavailable: {exc}")
                continue
            data = (root / relative).read_bytes()
            artifacts.append(
                ArtifactRecord(path=relative, sha256=sha256_bytes(data), status="generated")
            )

    write("README.md", _bundle_readme(design, selected_scope, artifacts, formats))
    manifest = ExportBundleManifest(
        project=design.project,
        revision=revision,
        bundle_id=bundle_id,
        created_at=datetime.now(UTC),
        formats=sorted(formats),
        artifacts=artifacts,
        design_sha256=revision_manifest.design_sha256,
    )
    write("manifest.json", json_bytes(manifest))
    store.write_export_metadata("current")
    stale = store.root / "exports"
    if stale.is_dir():
        shutil.rmtree(stale)
    return root, manifest


def _markdown_folder(name: str) -> str:
    if name == "AI_Enterprise_PRD.md":
        return "documents/requirements"
    return "documents/components"


def _drawio_pages(
    views: list[View], graph: ArchitectureGraph
) -> list[tuple[str, str, ArchitectureGraph | Scene]]:
    pages: list[tuple[str, str, ArchitectureGraph | Scene]] = []
    for item in views:
        if item.key == "architecture":
            pages.append((item.key, item.title, graph))
        else:
            pages.append((item.key, item.title, item.scene))
    return pages


def _write_package_diagrams(
    write: Any,
    write_png: Any,
    formats: set[str],
    package: str,
    views: list[View],
    graph: ArchitectureGraph,
    package_only: bool,
) -> None:
    if not views:
        return
    if "drawio" in formats:
        source = drawio_document(_drawio_pages(views, graph))
        ET.fromstring(source)
        write(f"diagrams/{package}.drawio", source)
    if package_only:
        if "mmd" in formats:
            for item in views:
                write(f"diagrams/{package}/{item.key}.mmd", item.mermaid)
        if "svg" in formats:
            for item in views:
                source = to_svg(item.scene)
                ET.fromstring(source)
                write(f"diagrams/{package}/{item.key}.svg", source)
        if "png" in formats:
            for item in views:
                write_png(f"diagrams/{package}/{item.key}.png", item.scene)


def _bundle_readme(
    design: EnterpriseDesign,
    scope: list[str],
    artifacts: list[ArtifactRecord],
    formats: set[str],
) -> str:
    del formats
    generated = {item.path for item in artifacts if item.status == "generated"}

    def listed(*paths: str) -> list[str]:
        return [f"- `{path}`" for path in paths if path in generated]

    lines = [
        f"# {design.project} export",
        "",
        "Design assets only; nothing in this bundle is deployed. Files are grouped by use.",
        "",
        "## Open these first",
        "",
    ]
    review = listed(
        f"{REVIEW_FILES['hld']}.pdf",
        f"{REVIEW_FILES['hld']}.md",
        f"{REVIEW_FILES['lld']}.pdf",
        f"{REVIEW_FILES['lld']}.md",
        f"{REVIEW_FILES['master']}.pdf",
        f"{REVIEW_FILES['master']}.md",
    )
    lines += review or ["- No review documents in this scoped export."]
    lines += [
        "",
        "## Folders",
        "",
        "- `documents/High_Level_Design` — what the system is, tools, and the request path",
        "- `documents/Low_Level_Design` — interactive hops in full; other paths as compact tables",
        "- `documents/Master_Design` — feature catalog, build order, and sprint slices",
        "- `documents/requirements/` — product requirements",
        "- `documents/components/` — one document per designed component",
        "- `diagrams/` — mermaid, svg, png, and draw.io files, including `hld.drawio` and `lld.drawio`",
        "- `config/` — policies, gateway files, and custom-runtime contracts",
        "- `infrastructure/` and `workloads/` — generated IaC; ArchAI never applies it",
        "- `state/` — canonical JSON for this revision",
        "- `sources/` — input files used for the design",
        "",
        f"Export scope: {', '.join(scope)}.",
        "",
    ]
    return "\n".join(lines)


def _pdf(
    path: Path, markdown: str, title: str, design: EnterpriseDesign, scenes: dict[str, Any]
) -> None:
    from archai.compilers.pdf import render_pdf

    path.parent.mkdir(parents=True, exist_ok=True)
    req = design.requirements
    sources = sorted({source_label(s.source) for s in design.components.values() if s.source})
    render_pdf(
        markdown,
        path,
        title=title,
        project=design.project,
        diagrams=scenes,
        subtitle=req.business_outcome,
        cover_rows=[
            ("Profile", f"{req.profile} · {req.region} · {req.topology}"),
            ("Completeness", "complete" if project_complete(design) else "partial"),
            ("Designed by", ", ".join(sources) or "deterministic baseline"),
            ("Deployment status", "design assets only; not deployed"),
        ],
    )


def _gateway_json(design: EnterpriseDesign) -> bytes:
    policy = design.routing_policy
    return json_bytes(
        {
            "control_ownership": control_ownership(design),
            "api_contracts": [item.model_dump(mode="json") for item in design.api_contracts],
            "aliases": [item.model_dump(mode="json") for item in design.model_aliases],
            "endpoints": [item.model_dump(mode="json") for item in design.endpoints],
            "routing_policy": policy.model_dump(mode="json") if policy else None,
            "attempt_limit": policy.max_attempts if policy else 2,
            "stream_replay": "forbidden-after-first-byte",
        }
    )


def _litellm_params(endpoint: Any) -> dict[str, Any]:
    provider = endpoint.provider.lower()
    env = endpoint.id.upper().replace("-", "_")
    deployment = endpoint.deployment_id
    if "azure" in provider:
        params: dict[str, Any] = {
            "model": f"azure/{deployment}",
            "api_base": f"os.environ/{env}_API_BASE",
            "api_version": f"os.environ/{env}_API_VERSION",
            "api_key": f"os.environ/{env}_API_KEY",
        }
    elif "bedrock" in provider:
        params = {"model": f"bedrock/{deployment}", "aws_region_name": f"os.environ/{env}_REGION"}
    elif "anthropic" in provider:
        params = {"model": f"anthropic/{deployment}", "api_key": f"os.environ/{env}_API_KEY"}
    elif "vertex" in provider or "google" in provider:
        params = {
            "model": f"vertex_ai/{deployment}",
            "vertex_project": f"os.environ/{env}_VERTEX_PROJECT",
            "vertex_location": f"os.environ/{env}_VERTEX_LOCATION",
        }
    elif provider == "openai":
        params = {"model": f"openai/{deployment}", "api_key": f"os.environ/{env}_API_KEY"}
    else:
        params = {
            "model": f"openai/{deployment}",
            "api_base": f"os.environ/{env}_API_BASE",
            "api_key": f"os.environ/{env}_API_KEY",
        }
    params["rpm"] = endpoint.rpm
    params["tpm"] = endpoint.tpm
    return params


def litellm_yaml(design: EnterpriseDesign) -> str:
    endpoints = {item.id: item for item in design.endpoints}
    model_list: list[dict[str, Any]] = []
    fallbacks: list[dict[str, list[str]]] = []
    for alias in design.model_aliases:
        if not alias.endpoint_ids:
            continue
        primary = endpoints[alias.endpoint_ids[0]]
        mode = "embedding" if "embeddings" in alias.required_capabilities else "chat"
        model_list.append(
            {
                "model_name": alias.id,
                "litellm_params": _litellm_params(primary),
                "model_info": {"id": primary.id, "mode": mode},
            }
        )
        names = []
        for index, endpoint_id in enumerate(alias.fallback_endpoint_ids, start=1):
            name = f"{alias.id}-fallback-{index}"
            endpoint = endpoints[endpoint_id]
            model_list.append(
                {
                    "model_name": name,
                    "litellm_params": _litellm_params(endpoint),
                    "model_info": {"id": endpoint.id, "mode": mode},
                }
            )
            names.append(name)
        if names:
            fallbacks.append({alias.id: names})
    attempts = design.routing_policy.max_attempts if design.routing_policy else 2
    router: dict[str, Any] = {
        "routing_strategy": "simple-shuffle",
        "num_retries": max(0, min(2, attempts - 1)),
        "timeout": 120,
        "allowed_fails": 3,
        "cooldown_time": 30,
    }
    if fallbacks:
        router["fallbacks"] = fallbacks
    header = (
        "# LiteLLM proxy configuration generated by ArchAI.\n"
        "# Deployment IDs marked USER_SUPPLIED are account inputs; secrets are environment\n"
        "# references only. The AI gateway is the single provider-retry owner. Budget\n"
        "# reservations are enforced by the model-admission service, not by this file.\n"
    )
    return header + yaml.safe_dump(
        {
            "model_list": model_list,
            "router_settings": router,
            "litellm_settings": {"drop_params": False},
            "general_settings": {"master_key": "os.environ/LITELLM_MASTER_KEY"},
        },
        sort_keys=False,
    )


def _policy_files(design: EnterpriseDesign) -> dict[str, tuple[str, Any]]:
    files: dict[str, tuple[str, Any]] = {}
    for name, component, value in (
        ("budgets.yaml", "budget", design.budget_policy),
        ("cache_policy.yaml", "cache", design.cache_policy),
        ("queue_policy.yaml", "resilience", design.queue_policy),
        ("identity_policy.yaml", "auth", design.identity_policy),
        ("guardrails.yaml", "guard", design.guardrails),
    ):
        if value:
            if isinstance(value, list):
                files[name] = (component, [item.model_dump(mode="json") for item in value])
            else:
                files[name] = (component, value.model_dump(mode="json"))
    return files


def _integration_contracts(design: EnterpriseDesign) -> str:
    custom = [c for c in design.guardrails if c.enforcement == "custom-runtime-required"]
    lines = [
        "# Custom runtime integration contracts",
        "",
        "Generated gateway files do not implement these application responsibilities. Each is a",
        "`custom-runtime-required` contract that the target application must implement and test.",
        "",
        "## Budget reservation service",
        "",
        "| Operation | Contract |",
        "| --- | --- |",
        "| `POST /internal/budget/reservations` | Atomically reserve a bounded attempt across "
        "organization, department, and application scopes; returns `reservation_id` or 409 |",
        "| `POST /internal/budget/reservations/{id}/dispatch` | Durable dispatch record (outbox) |",
        "| `POST /internal/budget/reservations/{id}/settle` | Idempotent settlement with reported "
        "usage |",
        "| `POST /internal/budget/reservations/{id}/unresolved` | Keep liability when usage is "
        "unknown |",
        "| `POST /internal/budget/reservations/{id}/release` | Only when dispatch provably never "
        "happened |",
        "",
        "## Other responsibilities",
        "",
        "- Trusted-claim-to-tenant/budget mapping and object-level authorization.",
        "- Tool authorization and human approval bound to exact arguments.",
        "- Provider eligibility filtering for residency, capability, evaluation, quota, and "
        "deadline.",
        "- Idempotent outbox/job state transitions and uncertain side-effect handling.",
    ]
    if custom:
        lines += [
            "",
            "## Guardrail controls",
            "",
            "| ID | Stage | Control | Owner |",
            "| --- | --- | --- | --- |",
        ]
        lines += [f"| `{c.id}` | {c.stage} | {c.control} | {c.owner} |" for c in custom]
    lines += [
        "",
        "These controls are `custom-runtime-required`; the generated assets are reviewed "
        "design inputs only.",
    ]
    return "\n".join(lines) + "\n"
