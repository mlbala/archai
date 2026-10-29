"""Low-level design: one section per request hop, compiled from canonical state."""

from __future__ import annotations

from archai.compilers.hops import Hop, other_paths, request_hops
from archai.compilers.report import (
    DISCLAIMER,
    diagram_block,
    project_complete,
    scale_body,
    source_label,
    table,
)
from archai.compilers.views import View, all_views
from archai.schemas.models import (
    ArchitectureGraph,
    EnterpriseDesign,
    ValidationDiagnostic,
)


def low_level_views(design: EnterpriseDesign, graph: ArchitectureGraph) -> list[View]:
    return all_views(design, graph)


def low_level_design_document(
    design: EnterpriseDesign,
    graph: ArchitectureGraph,
    diagnostics: list[ValidationDiagnostic],
) -> str:
    del diagnostics
    req = design.requirements
    views = low_level_views(design, graph)
    by_key = {view.key: view for view in views}
    sources = sorted({source_label(s.source) for s in design.components.values() if s.source})
    hops = request_hops(design)
    lines = [
        "# Low-Level Design",
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
        "This is the implementation review document for this revision. Each step is a hop "
        "the owning service must implement. The high-level design has the system picture. "
        "The master design has the build order. Component documents live in "
        "`documents/components/`. Open `diagrams/lld.drawio` in diagrams.net.",
        "",
        "## 1. Service index",
        "",
    ]
    if design.services:
        lines += table(
            ["ID", "Service", "Kind", "Technology", "Exposes", "Depends on"],
            [
                [
                    f"`{service.id}`",
                    service.name,
                    service.kind,
                    service.technology or "—",
                    ", ".join(service.exposes) or "—",
                    ", ".join(service.depends_on) or "—",
                ]
                for service in design.services
            ],
        )
        lines += ["", f"{len(graph.nodes)} tools on the architecture graph.", ""]
    else:
        lines.append("_No services on this revision._")
    lines += ["", "## 2. Interactive request", ""]
    if "request" in by_key:
        lines += diagram_block(by_key["request"], "###")
    lines.append("Implement these hops in order. IDs match the service index.")
    lines.append("")
    lines += _hop_sections(hops, "###")
    lines += ["## 3. Other paths", ""]
    lines.append(
        "Compact hop tables compiled from the same contracts, workflows, and policies as "
        "the diagrams. Interactive hops above carry owner, interface, payload, and failure."
    )
    lines.append("")
    used_views: set[str] = set()
    for walk in other_paths(design):
        lines += [f"### {walk.title}", ""]
        if walk.view_key and walk.view_key in by_key:
            lines += diagram_block(by_key[walk.view_key], "####")
            used_views.add(walk.view_key)
        if walk.hops:
            lines += table(
                ["Step", "From", "To", "Action", "Owner"],
                [[hop.number, hop.source, hop.target, hop.action, hop.owner] for hop in walk.hops],
            )
            lines.append("")
    for key in ("budget", "recovery"):
        if key in by_key and key not in used_views:
            lines += diagram_block(by_key[key], "###")
    if design.api_contracts:
        lines += ["### API catalog", ""]
        lines += table(
            ["ID", "Method", "Path", "Auth", "Service", "Streaming"],
            [
                [
                    f"`{contract.id}`",
                    contract.method,
                    contract.path,
                    contract.auth,
                    contract.service_id or "—",
                    "yes" if contract.streaming else "no",
                ]
                for contract in design.api_contracts
            ],
        )
        lines.append("")
    if design.data_stores:
        lines += ["### Data stores", ""]
        lines += table(
            ["ID", "Store", "Kind", "Region", "Owner", "Retention (days)"],
            [
                [
                    f"`{store.id}`",
                    store.name,
                    store.kind,
                    store.region,
                    store.owner_service or "—",
                    str(store.retention_days),
                ]
                for store in design.data_stores
            ],
        )
        lines.append("")
    lines += ["## 4. Scale-up", ""]
    if "scale" in by_key:
        lines += diagram_block(by_key["scale"], "###")
    lines += scale_body(design)
    lines += [
        "",
        "## 5. Custom runtime work",
        "",
        "Generated gateway files do not implement budget reservation, object-level "
        "authorization, approval binding, or provider eligibility filtering. Those "
        "contracts are listed in `config/integration_contracts.md`.",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _hop_sections(hops: list[Hop], heading: str) -> list[str]:
    lines: list[str] = []
    for hop in hops:
        lines += [
            f"{heading} Step {hop.number} — {hop.source} → {hop.target}",
            "",
            hop.action,
            "",
            *table(
                ["Field", "Value"],
                [
                    ["Owner", hop.owner],
                    ["Interface", hop.interface],
                    ["Payload", "; ".join(hop.payload) or "—"],
                    ["Data touched", "; ".join(hop.data) or "—"],
                    ["Failure", hop.failure],
                ],
            ),
            "",
        ]
    return lines
