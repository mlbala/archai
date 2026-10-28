from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from functools import partial
from html import escape
from pathlib import Path
from typing import Any, cast

import yaml

from archai.compilers.diagram import drawio, mermaid, png, svg
from archai.compilers.report import complete_document, component_document
from archai.ingestion import sha256_bytes
from archai.persistence.store import ProjectStore, json_bytes, new_bundle_id
from archai.schemas.models import (
    ArtifactRecord,
    ExportBundleManifest,
)

CORE_FORMATS = {"md", "json", "yaml", "mmd", "drawio", "svg", "tf", "xml"}
ALL_FORMATS = CORE_FORMATS | {"png", "pdf"}


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


def export_revision(
    store: ProjectStore,
    revision: int,
    formats: set[str],
    scope: list[str] | None = None,
) -> tuple[Path, ExportBundleManifest]:
    design = store.load_design(revision)
    graph = store.load_graph(revision)
    revision_manifest = store.load_manifest(revision)
    selected_scope = scope or revision_manifest.selected_scope
    diagnostics = revision_manifest.diagnostics
    bundle_id = new_bundle_id()
    root = store.root / "exports" / f"{revision:04d}" / bundle_id
    root.mkdir(parents=True, mode=0o700)
    artifacts: list[ArtifactRecord] = []

    def write(relative: str, content: str | bytes) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode() if isinstance(content, str) else content
        path.write_bytes(data)
        artifacts.append(
            ArtifactRecord(path=relative, sha256=sha256_bytes(data), status="generated")
        )

    if "json" in formats:
        write("enterprise_design.json", json_bytes(design))
        write("architecture_graph.json", json_bytes(graph))
        write(
            "validation_report.json",
            json_bytes({"diagnostics": [item.model_dump(mode="json") for item in diagnostics]}),
        )
        write("api_gateway_and_routing_config.json", _gateway_json(design))
        if design.costs or design.capacity:
            write(
                "capacity_and_cost.json",
                json_bytes(
                    {
                        "capacity": design.capacity.model_dump(mode="json")
                        if design.capacity
                        else None,
                        "estimates": [item.model_dump(mode="json") for item in design.costs],
                    }
                ),
            )
        if design.deployment:
            write(
                "cloud_bom.json",
                json_bytes(
                    {
                        "profile": design.deployment.model_dump(mode="json"),
                        "validation_level": "generated design only",
                    }
                ),
            )
    if "md" in formats:
        for component in selected_scope:
            if component == "doc":
                continue
            if component in design.components:
                name = component.title().replace("_", "") + "_Design.md"
                if component == "guard":
                    name = "Guardrails_Design.md"
                elif component == "infra":
                    name = "Infrastructure_Design.md"
                write(
                    f"documents/{name}", component_document(component, design, graph, diagnostics)
                )
        write("Complete_AI_System_Design.md", complete_document(design, graph, diagnostics))
        write("integration_contracts.md", _integration_contracts(design))
    if "yaml" in formats:
        if design.model_aliases:
            write("litellm.yaml", _litellm_yaml(design))
        for name, value in _policy_files(design).items():
            write(f"policies/{name}", yaml.safe_dump(value, sort_keys=True))
    if "xml" in formats and design.requirements.profile.startswith("azure"):
        xml = _apim_xml()
        ET.fromstring(xml)
        write("apim_policies.xml", xml)
    elif "xml" in formats:
        artifacts.append(
            ArtifactRecord(
                path="apim_policies.xml",
                sha256=None,
                status="not_applicable",
                reason="APIM is not selected",
            )
        )
    if "mmd" in formats:
        write("diagrams/architecture_diagram.mmd", mermaid(graph))
    if "drawio" in formats:
        source = drawio(graph)
        ET.fromstring(source)
        write("diagrams/architecture_diagram.drawio", source)
    svg_source = svg(graph)
    if "svg" in formats:
        ET.fromstring(svg_source)
        write("diagrams/architecture_diagram.svg", svg_source)
    if "tf" in formats:
        if design.requirements.profile == "agnostic":
            artifacts.append(
                ArtifactRecord(
                    path="infrastructure/main.tf",
                    sha256=None,
                    status="not_applicable",
                    reason="agnostic profile has no fake universal Terraform",
                )
            )
        else:
            write("infrastructure/main.tf", _terraform(design.requirements.profile))
            write("infrastructure/variables.tf", _terraform_variables())
    if "png" in formats:
        try:
            png_bytes = _render_png(svg_source, graph)
            write("diagrams/architecture_diagram.png", png_bytes)
        except (ImportError, OSError) as exc:
            artifacts.append(
                ArtifactRecord(
                    path="diagrams/architecture_diagram.png",
                    sha256=None,
                    status="failed",
                    reason=f"optional CairoSVG renderer unavailable: {exc}",
                )
            )
    if "pdf" in formats:
        try:
            pdf_path = root / "Complete_AI_System_Design.pdf"
            _complete_pdf(
                pdf_path,
                complete_document(design, graph, diagnostics),
                root / "diagrams" / "architecture_diagram.png",
                design.project,
            )
            data = pdf_path.read_bytes()
            artifacts.append(
                ArtifactRecord(
                    path="Complete_AI_System_Design.pdf",
                    sha256=sha256_bytes(data),
                    status="generated",
                )
            )
        except ImportError as exc:
            artifacts.append(
                ArtifactRecord(
                    path="Complete_AI_System_Design.pdf",
                    sha256=None,
                    status="failed",
                    reason=f"optional ReportLab renderer unavailable: {exc}",
                )
            )

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
    store.write_export_metadata(bundle_id)
    return root, manifest


def _gateway_json(design: Any) -> bytes:
    return json_bytes(
        {
            "control_ownership": {
                "authentication": "enterprise-api-gateway",
                "request_limits": "enterprise-api-gateway",
                "budget_reservation": "application-model-admission",
                "provider_retry": "ai-gateway",
                "cache_authorization": "application",
                "usage_settlement": "application-model-admission",
            },
            "aliases": [item.model_dump(mode="json") for item in design.model_aliases],
            "endpoints": [item.model_dump(mode="json") for item in design.endpoints],
            "attempt_limit": 2,
            "stream_replay": "forbidden-after-first-byte",
        }
    )


def _litellm_yaml(design: Any) -> str:
    model_list = []
    for alias in design.model_aliases:
        for endpoint_id in alias.endpoint_ids:
            endpoint = next(item for item in design.endpoints if item.id == endpoint_id)
            model_list.append(
                {
                    "model_name": alias.id,
                    "litellm_params": {
                        "model": endpoint.deployment_id,
                        "api_key": f"os.environ/{endpoint.id.upper().replace('-', '_')}_API_KEY",
                    },
                }
            )
    return yaml.safe_dump(
        {
            "model_list": model_list,
            "router_settings": {"num_retries": 1, "allowed_fails": 2, "cooldown_time": 30},
        },
        sort_keys=False,
    )


def _policy_files(design: Any) -> dict[str, Any]:
    files: dict[str, Any] = {}
    for name, value in (
        ("budgets.yaml", design.budget_policy),
        ("cache_policy.yaml", design.cache_policy),
        ("queue_policy.yaml", design.queue_policy),
        ("identity_policy.yaml", design.identity_policy),
        ("guardrails.yaml", design.guardrails),
    ):
        if value:
            if isinstance(value, list):
                files[name] = [item.model_dump(mode="json") for item in value]
            else:
                files[name] = value.model_dump(mode="json")
    return files


def _apim_xml() -> str:
    return """<policies>
  <inbound>
    <base />
    <validate-jwt header-name="Authorization" failed-validation-httpcode="401" require-expiration-time="true" require-scheme="Bearer">
      <openid-config url="{{entra-openid-config-url}}" />
      <audiences><audience>{{api-audience}}</audience></audiences>
    </validate-jwt>
    <rate-limit-by-key calls="{{rpm-limit}}" renewal-period="60" counter-key="@(context.Principal?.Id ?? &quot;anonymous&quot;)" />
  </inbound>
  <backend><base /></backend>
  <outbound><base /></outbound>
  <on-error><base /></on-error>
</policies>
"""


def _integration_contracts(design: Any) -> str:
    return """# Custom runtime integration contracts

Generated gateway files do not implement these application responsibilities:

- Atomic hierarchical monetary reservations and durable settlement/reconciliation.
- Trusted-claim-to-tenant/budget mapping and object-level authorization.
- Tool authorization and human approval bound to exact arguments.
- Provider eligibility filtering for residency, capability, evaluation, quota, and deadline.
- Idempotent outbox/job state transitions and uncertain side-effect handling.

These controls are `custom-runtime-required`; the generated assets are reviewed design inputs only.
"""


def _terraform(profile: str) -> str:
    provider = "azurerm" if profile.startswith("azure") else "aws"
    return f"""terraform {{
  required_version = ">= 1.7, < 2.0"
  required_providers {{
    {provider} = {{
      source  = "hashicorp/{provider}"
      version = "~> 4.0"
    }}
  }}
}}

# Reviewed design scaffold. Add approved account/network/SKU inputs before planning.
# ArchAI never runs terraform apply.
"""


def _terraform_variables() -> str:
    return """variable "application_image" {
  description = "User-owned immutable application image reference"
  type        = string
  validation {
    condition     = length(trimspace(var.application_image)) > 0 && !startswith(var.application_image, "example")
    error_message = "Supply a real user-owned application image reference."
  }
}
"""


def _complete_pdf(path: Path, markdown: str, diagram_path: Path, project: str) -> None:
    from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
    from reportlab.lib.styles import getSampleStyleSheet  # type: ignore[import-untyped]
    from reportlab.lib.units import mm  # type: ignore[import-untyped]
    from reportlab.pdfgen import canvas  # type: ignore[import-untyped]
    from reportlab.platypus import (  # type: ignore[import-untyped]
        Image,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    styles = getSampleStyleSheet()
    styles["Title"].fontName = "Helvetica-Bold"
    styles["Title"].fontSize = 24
    styles["Title"].leading = 29
    styles["Heading1"].spaceBefore = 14
    styles["Heading1"].spaceAfter = 8
    styles["Heading2"].spaceBefore = 10
    styles["BodyText"].fontSize = 9.5
    styles["BodyText"].leading = 13
    styles["Bullet"].fontSize = 9.5
    styles["Bullet"].leading = 13
    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title="Complete AI System Design",
        author="",
        subject=f"ArchAI reviewed design for {project}",
    )
    story: list[Any] = []
    inserted_diagram = False
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            story.append(Spacer(1, 3 * mm))
            continue
        if line.startswith("# "):
            if story:
                story.append(PageBreak())
            story.append(Paragraph(escape(line[2:]), styles["Title"]))
            continue
        if line.startswith("## "):
            story.append(Paragraph(escape(line[3:]), styles["Heading1"]))
            if not inserted_diagram and diagram_path.exists() and "Outcome" in line:
                story.append(Spacer(1, 2 * mm))
                story.append(
                    Image(str(diagram_path), width=174 * mm, height=39 * mm, kind="proportional")
                )
                story.append(Paragraph("Canonical architecture view", styles["Italic"]))
                inserted_diagram = True
            continue
        if line.startswith("### "):
            story.append(Paragraph(escape(line[4:]), styles["Heading2"]))
            continue
        if line.startswith("- "):
            story.append(Paragraph(escape(line[2:]), styles["Bullet"], bulletText="-"))
            continue
        if line.startswith("> "):
            story.append(Paragraph(f"<i>{escape(line[2:])}</i>", styles["BodyText"]))
            continue
        cleaned = escape(line).replace("`", "")
        cleaned = cleaned.replace("**", "")
        story.append(Paragraph(cleaned, styles["BodyText"]))

    def footer(pdf: Any, doc: Any) -> None:
        pdf.saveState()
        pdf.setFont("Helvetica", 8)
        pdf.setFillColorRGB(0.35, 0.39, 0.45)
        pdf.drawString(18 * mm, 10 * mm, f"ArchAI - {project} - design assets only")
        pdf.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        pdf.restoreState()

    document.build(
        story,
        onFirstPage=footer,
        onLaterPages=footer,
        canvasmaker=partial(canvas.Canvas, invariant=1),
    )


def _render_png(svg_source: str, graph: Any) -> bytes:
    try:
        import cairosvg  # type: ignore[import-untyped]

        return cast(bytes, cairosvg.svg2png(bytestring=svg_source.encode()))
    except (ImportError, OSError) as cairo_error:
        try:
            return png(graph)
        except ImportError as pillow_error:
            raise OSError(
                f"CairoSVG and Pillow renderers are unavailable: {cairo_error}; {pillow_error}"
            ) from pillow_error
