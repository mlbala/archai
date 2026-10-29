"""High-level design compiled from canonical state: context, tools, and request path."""

from __future__ import annotations

from archai.application.registry import COMPILED_COMPONENTS, COMPONENTS
from archai.compilers.hops import request_flow, trust_boundaries
from archai.compilers.report import (
    DISCLAIMER,
    bullets,
    diagram_block,
    project_complete,
    source_label,
    table,
)
from archai.compilers.views import View, all_views
from archai.schemas.models import (
    ArchitectureGraph,
    ComponentStatus,
    EnterpriseDesign,
    ValidationDiagnostic,
)

HLD_VIEW_KEYS = ("context", "architecture", "request", "deployment")


def high_level_views(design: EnterpriseDesign, graph: ArchitectureGraph) -> list[View]:
    by_key = {view.key: view for view in all_views(design, graph)}
    return [by_key[key] for key in HLD_VIEW_KEYS if key in by_key]


def high_level_design_document(
    design: EnterpriseDesign,
    graph: ArchitectureGraph,
    diagnostics: list[ValidationDiagnostic],
) -> str:
    del diagnostics
    req = design.requirements
    views = {view.key: view for view in high_level_views(design, graph)}
    sources = sorted({source_label(s.source) for s in design.components.values() if s.source})
    lines = [
        "# High-Level Design",
        "",
        *table(
            ["Field", "Value"],
            [
                ["Project", f"`{design.project}`"],
                ["Completeness", "complete" if project_complete(design) else "partial"],
                [
                    "Hosting",
                    f"{req.profile} in {req.region} ({req.topology})",
                ],
                ["Deployment status", "design assets only; not deployed"],
                ["Designed by", ", ".join(sources) or "deterministic baseline"],
            ],
        ),
        "",
        DISCLAIMER,
        "",
        "This is the architecture review document for this revision. It answers what the "
        "system is, which tools it uses, and how a request moves. The low-level design walks "
        "each hop. The master design is the build order. `Complete_AI_System_Design` is the "
        "archive of every component. Open `system.drawio` in this folder in diagrams.net.",
        "",
        "## 1. Context",
        "",
        req.business_outcome or "_No business outcome recorded._",
        "",
    ]
    lines += bullets(
        [
            f"Users: {', '.join(req.users) or 'unspecified'}",
            f"Channels: {', '.join(req.client_channels) or 'unspecified'}",
            f"Archetypes: {', '.join(req.archetypes) or 'unspecified'}",
            f"Region and residency: {req.region}; {req.data_residency}",
            f"Identity: {req.identity_provider or 'not selected'}",
        ]
    )
    skipped = [
        COMPONENTS[name].title
        for name, state in design.components.items()
        if name in COMPONENTS
        and name not in COMPILED_COMPONENTS
        and state.status == ComponentStatus.not_applicable
    ]
    if skipped:
        lines += ["", "Out of scope on this revision:", ""]
        lines += bullets(skipped)
    if "context" in views:
        lines += ["", *diagram_block(views["context"], "###")]
    lines += ["## 2. System architecture", ""]
    if "architecture" in views:
        lines += diagram_block(views["architecture"], "###")
    lines.append("Each row is a tool on the request path or a store it uses.")
    lines.append("")
    lines += table(
        ["Lane", "Tool", "Kind", "Technology"],
        [[node.lane, node.label, node.kind, _technology(design, node.id)] for node in graph.nodes],
    )
    lines += ["", "## 3. Request path", ""]
    if "request" in views:
        lines += diagram_block(views["request"], "###")
    lines.append("A user request moves through these tools in order.")
    lines.append("")
    lines += table(["Step", "From", "To", "Action"], _request_rows(design))
    lines += ["", "## 4. Trust boundaries", ""]
    lines.append(
        "The enterprise API gateway is the public trust boundary. Managed model APIs sit "
        "outside it. Budget reservation, object-level authorization, and tool approval stay "
        "in the application. Rows appear only for controls that exist on this revision."
    )
    lines.append("")
    boundaries = trust_boundaries(design)
    if boundaries:
        lines += table(
            ["Control", "Owner", "Boundary"],
            [[control, owner, bound] for control, owner, bound in boundaries],
        )
    else:
        lines.append("_No trust-boundary controls are in scope on this revision._")
    lines += ["", "## 5. Deployment", ""]
    if "deployment" in views:
        lines += diagram_block(views["deployment"], "###")
    if design.deployment:
        dep = design.deployment
        lines += table(
            ["Field", "Value"],
            [
                ["Profile", dep.name],
                ["Region", dep.region],
                ["Compute", dep.compute or "profile default"],
                ["Network", ", ".join(dep.networking) or "profile default"],
            ],
        )
    else:
        lines.append("_No cloud deployment profile is in scope for this revision._")
    lines += ["", "## 6. Decisions carried into the architecture", ""]
    if design.decisions:
        lines += table(
            ["ID", "Decision", "Rationale"],
            [[item.id, item.title, item.rationale] for item in design.decisions],
        )
    else:
        lines.append("_No architecture decisions recorded on this revision._")
    return "\n".join(lines).rstrip() + "\n"


def _technology(design: EnterpriseDesign, node_id: str) -> str:
    for service in design.services:
        if service.id == node_id:
            return service.technology or service.kind
    for store in design.data_stores:
        if store.id == node_id:
            return store.kind
    for endpoint in design.endpoints:
        if endpoint.id == node_id:
            return endpoint.provider
    return "—"


def _request_rows(design: EnterpriseDesign) -> list[list[str]]:
    participants, messages = request_flow(design)
    labels = {pid: label for pid, label, _style in participants}
    return [
        [str(index), labels.get(source, source), labels.get(target, target), action]
        for index, (source, target, action, _dashed) in enumerate(messages, start=1)
    ]
