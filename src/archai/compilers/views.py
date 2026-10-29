"""Architecture views generated deterministically from canonical state.

Every view has Mermaid source (embedded in Markdown and written under diagrams/mermaid/).
PDF documents embed a matching layout drawing; SVG and PNG files are not generated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from archai.application.designer import LANES
from archai.compilers.hops import (
    SequenceSpec,
    async_sequence,
    fallback_sequence,
    identity_sequences,
    request_sequence,
)
from archai.compilers.scene import (
    LayoutEdge,
    LayoutNode,
    Scene,
    flow_scene,
    group_scene,
    layered_scene,
    sequence_scene,
)
from archai.domain.scale import replica_ceiling, scale_targets
from archai.schemas.models import ArchitectureGraph, EnterpriseDesign

STYLE_BY_KIND = {
    "client": "client",
    "identity": "identity",
    "frontend": "gateway",
    "gateway": "gateway",
    "application": "application",
    "orchestration": "application",
    "retrieval": "application",
    "tool-executor": "application",
    "integration": "application",
    "policy": "policy",
    "ai-gateway": "ai",
    "managed-model": "model",
    "data": "data",
    "queue": "queue",
    "worker": "worker",
    "ingestion": "worker",
    "operations": "ops",
}


GENERIC_LABELS = {"calls", "reads/writes", "telemetry", "token signing keys"}


@dataclass
class View:
    key: str
    title: str
    description: str
    mermaid: str
    scene: Scene


def mid(value: str) -> str:
    return "N_" + re.sub(r"[^A-Za-z0-9]", "_", value)


def mlabel(text: str) -> str:
    cleaned = " ".join(str(text).split())
    return (
        cleaned.replace("&", "and")
        .replace('"', "#quot;")
        .replace("<", "#lt;")
        .replace(">", "#gt;")
        .replace("|", "/")
    )


def mmsg(text: str) -> str:
    return " ".join(str(text).split()).replace(";", ",").replace("#", "").replace("\n", " ")


# ---------------------------------------------------------------- architecture


def architecture_view(design: EnterpriseDesign, graph: ArchitectureGraph) -> View:
    lane_index = {lane: number for number, lane in enumerate(LANES)}
    nodes = [
        LayoutNode(
            id=node.id,
            label=node.label,
            sublabel=_sublabel(design, node.id),
            column=lane_index.get(node.lane, 2),
            style=STYLE_BY_KIND.get(node.kind, "application"),
        )
        for node in graph.nodes
    ]
    edges = [
        LayoutEdge(
            source=edge.source,
            target=edge.target,
            label=None if edge.kind == "telemetry" or edge.label in GENERIC_LABELS else edge.label,
            dashed=edge.kind in {"identity", "telemetry", "fallback"},
        )
        for edge in graph.edges
    ]
    scene = layered_scene("System architecture", nodes, edges, list(LANES))
    lines = ["flowchart LR"]
    for lane in LANES:
        members = [node for node in graph.nodes if node.lane == lane]
        if not members:
            continue
        lines.append(f'    subgraph {mid(lane)}["{mlabel(lane)}"]')
        for node in members:
            shape = ('[("', '")]') if node.kind == "data" else ('["', '"]')
            lines.append(f"        {mid(node.id)}{shape[0]}{mlabel(node.label)}{shape[1]}")
        lines.append("    end")
    for edge in graph.edges:
        arrow = "-.->" if edge.kind in {"identity", "telemetry", "fallback"} else "-->"
        lines.append(f'    {mid(edge.source)} {arrow}|"{mlabel(edge.label)}"| {mid(edge.target)}')
    return View(
        "architecture",
        "System architecture",
        "Services, data stores, managed model endpoints, and trust lanes from canonical state.",
        "\n".join(lines) + "\n",
        scene,
    )


def context_view(design: EnterpriseDesign) -> View:
    """Users, identity, the application, and managed models — one box each."""
    req = design.requirements
    users = ", ".join(req.users[:3]) or "Users"
    idp = (
        design.identity_policy.idp
        if design.identity_policy
        else (req.identity_provider or "Identity provider")
    )
    cloud = design.deployment.hosting_cloud if design.deployment else req.profile
    region = design.deployment.region if design.deployment else req.region
    providers = ", ".join(req.allowed_target_providers[:3]) or "Managed models"
    app = design.project.replace("-", " ")
    left = [(users, "client")]
    channels = ", ".join(req.client_channels[:2])
    if channels:
        left.append((channels, "client"))
    groups = [(cloud, [(app, region)], "application")]
    right: list[tuple[str, str, str]] = []
    if design.identity_policy or req.identity_provider:
        right.append((idp, "sign-in tokens", "identity"))
    right.append((providers, "managed APIs", "model"))
    scene = group_scene("System context", groups, f"{cloud} · {region}", left, right)
    lines = [
        "flowchart LR",
        f'    users["{mlabel(users)}"] --> app["{mlabel(app)}"]',
    ]
    if design.identity_policy or req.identity_provider:
        lines.append(f'    idp["{mlabel(idp)}"] -.->|"{mlabel("tokens")}"| app')
    lines.append(f'    app --> models["{mlabel(providers)}"]')
    return View(
        "context",
        "System context",
        "Who uses the application, where it is hosted, and which identity and model "
        "providers sit outside the trust boundary.",
        "\n".join(lines) + "\n",
        scene,
    )


def _sublabel(design: EnterpriseDesign, node_id: str) -> str | None:
    for service in design.services:
        if service.id == node_id:
            return service.technology
    for store in design.data_stores:
        if store.id == node_id:
            return store.kind
    for endpoint in design.endpoints:
        if endpoint.id == node_id:
            return endpoint.region
    return None


# ---------------------------------------------------------------- request sequence


def request_view(design: EnterpriseDesign) -> View:
    spec = request_sequence(design)
    return _from_spec(spec)


def _from_spec(spec: SequenceSpec) -> View:
    messages = [(item.source, item.target, item.action, item.dashed) for item in spec.steps]
    return _sequence(spec.key, spec.title, spec.description, spec.participants, messages)


def _sequence(
    key: str,
    title: str,
    description: str,
    participants: list[tuple[str, str, str]],
    messages: list[tuple[str, str, str, bool]],
) -> View:
    lines = ["sequenceDiagram", "    autonumber"]
    for pid, label, _style in participants:
        lines.append(f"    participant {pid} as {mmsg(label)}")
    for source, target, label, dashed in messages:
        arrow = "-->>" if dashed else "->>"
        lines.append(f"    {source}{arrow}{target}: {mmsg(label)}")
    return View(
        key,
        title,
        description,
        "\n".join(lines) + "\n",
        sequence_scene(title, participants, messages),
    )


# ---------------------------------------------------------------- identity


def oauth_views(design: EnterpriseDesign) -> list[View]:
    return [_from_spec(spec) for spec in identity_sequences(design)]


# ---------------------------------------------------------------- deployment and data


def deployment_view(design: EnterpriseDesign) -> View | None:
    deployment = design.deployment
    if deployment is None:
        return None
    buckets: dict[str, list[tuple[str, str]]] = {
        "Ingress & identity": [],
        "Compute": [],
        "Messaging & data": [],
        "Security & operations": [],
    }
    for resource in deployment.resource_details:
        name = resource.service.lower()
        if any(
            word in name
            for word in (
                "vault",
                "secret",
                "monitor",
                "log",
                "insight",
                "watch",
                "telemetry",
                "defender",
                "sentinel",
                "kms",
                "otel",
            )
        ):
            bucket = "Security & operations"
        elif any(
            word in name
            for word in (
                "api management",
                "gateway",
                "front door",
                "alb",
                "ingress",
                "waf",
                "cdn",
                "load balancer",
            )
        ):
            bucket = "Ingress & identity"
        elif any(
            word in name
            for word in (
                "container",
                "aks",
                "eks",
                "kubernetes",
                "app service",
                "function",
                "compute",
                "lambda",
                "fargate",
            )
        ):
            bucket = "Compute"
        else:
            bucket = "Messaging & data"
        buckets[bucket].append((resource.service, resource.tier))
    hosting = "container app" if design.requirements.profile == "azure-aca" else "deployment"
    for workload in design.services:
        if workload.kind not in {"gateway", "operations"} and len(buckets["Compute"]) < 7:
            buckets["Compute"].append((workload.name, hosting))
    groups = [
        (name, items[:7], style)
        for (name, items), style in zip(
            buckets.items(), ("gateway", "application", "data", "ops"), strict=True
        )
        if items
    ]
    right = [
        (endpoint.provider, endpoint.region, "model")
        for endpoint in design.endpoints
        if "embeddings" not in endpoint.modalities
    ][:3]
    idp = design.identity_policy.idp if design.identity_policy else "Identity provider"
    left = [("Enterprise clients", "client"), (idp, "identity")]
    label = f"{deployment.hosting_cloud.upper()} · {deployment.region} · {deployment.name}"
    scene = group_scene("Deployment view", groups, label, left, right)
    lines = ["flowchart LR", '    clients["Enterprise clients"]', f'    idp["{mlabel(idp)}"]']
    lines.append(f'    subgraph cloud["{mlabel(label)}"]')
    for number, (name, items, _style) in enumerate(groups):
        lines.append(f'        subgraph g{number}["{mlabel(name)}"]')
        for row, (service, tier) in enumerate(items):
            lines.append(f'            r{number}_{row}["{mlabel(service)}<br/>{mlabel(tier)}"]')
        lines.append("        end")
    lines.append("    end")
    lines.append("    clients --> g0" if groups else "    clients --> cloud")
    lines.append("    idp -.-> cloud")
    for number, (provider, region, _style) in enumerate(right):
        lines.append(f'    m{number}["{mlabel(provider)}<br/>{mlabel(region)}"]')
        lines.append(f"    cloud {'-->' if number == 0 else '-.->'} m{number}")
    return View(
        "deployment",
        "Deployment view",
        "Cloud boundary, resource groups, and approved managed-model egress.",
        "\n".join(lines) + "\n",
        scene,
    )


def data_view(design: EnterpriseDesign) -> View | None:
    if not design.data_stores:
        return None
    store_ids = {store.id for store in design.data_stores}
    users = [
        service
        for service in design.services
        if set(service.depends_on) & store_ids or set(service.data_owned) & store_ids
    ]
    nodes = [
        LayoutNode(s.id, s.name, s.technology, 0, STYLE_BY_KIND.get(s.kind, "application"))
        for s in users
    ]
    nodes += [
        LayoutNode(store.id, store.name, store.kind, 1, "data") for store in design.data_stores
    ]
    edges = [
        LayoutEdge(service.id, store, "owns" if store in service.data_owned else "reads/writes")
        for service in users
        for store in dict.fromkeys([*service.data_owned, *service.depends_on])
        if store in store_ids
    ]
    scene = layered_scene("Data ownership", nodes, edges, ["Services", "Data stores"], 200, 90)
    lines = ["flowchart LR"]
    for node in nodes:
        shape = ('[("', '")]') if node.style == "data" else ('["', '"]')
        lines.append(f"    {mid(node.id)}{shape[0]}{mlabel(node.label)}{shape[1]}")
    for edge in edges:
        lines.append(f'    {mid(edge.source)} -->|"{edge.label}"| {mid(edge.target)}')
    return View(
        "data",
        "Data ownership",
        "Which services own or use each data store.",
        "\n".join(lines) + "\n",
        scene,
    )


# ---------------------------------------------------------------- policies and flows


BUDGET_STATES = [
    ("requested", "Requested", 0),
    ("rejected", "Rejected", 1),
    ("reserved", "Reserved", 1),
    ("released", "Released", 2),
    ("dispatched", "Dispatched", 2),
    ("settled", "Settled", 3),
    ("unresolved", "Unresolved", 3),
    ("reconciled", "Reconciled", 4),
]
BUDGET_TRANSITIONS = [
    ("requested", "rejected", "allowance/policy denied"),
    ("requested", "reserved", "atomic admission"),
    ("reserved", "released", "verified no dispatch"),
    ("reserved", "dispatched", "durable attempt record"),
    ("dispatched", "settled", "actual usage"),
    ("dispatched", "unresolved", "usage unknown"),
    ("unresolved", "reconciled", "billing evidence"),
]


def budget_view() -> View:
    nodes = [
        LayoutNode(
            key,
            label,
            None,
            column,
            "queue" if key in {"rejected", "unresolved"} else "policy",
        )
        for key, label, column in BUDGET_STATES
    ]
    edges = [LayoutEdge(a, b, label) for a, b, label in BUDGET_TRANSITIONS]
    scene = layered_scene("Budget reservation lifecycle", nodes, edges, None, 130, 70)
    lines = ["stateDiagram-v2", "    [*] --> Requested"]
    names = {key: label for key, label, _ in BUDGET_STATES}
    for a, b, label in BUDGET_TRANSITIONS:
        lines.append(f"    {names[a]} --> {names[b]}: {mmsg(label)}")
    for terminal in ("Rejected", "Released", "Settled", "Reconciled"):
        lines.append(f"    {terminal} --> [*]")
    return View(
        "budget",
        "Budget reservation lifecycle",
        "Dispatched attempts keep their liability until settled or reconciled.",
        "\n".join(lines) + "\n",
        scene,
    )


def _flow(key: str, title: str, description: str, steps: list[str], style: str) -> View:
    lines = ["flowchart LR"]
    for number, step in enumerate(steps):
        lines.append(f'    s{number}["{number + 1}. {mlabel(step)}"]')
    for number in range(len(steps) - 1):
        lines.append(f"    s{number} --> s{number + 1}")
    return View(key, title, description, "\n".join(lines) + "\n", flow_scene(title, steps, style))


def ingestion_view(design: EnterpriseDesign) -> View | None:
    if design.rag_pipeline is None:
        return None
    steps = list(design.rag_pipeline.ingestion_steps)
    return _flow(
        "ingestion",
        "Document ingestion pipeline",
        "Asynchronous ingestion with ACL metadata and index versioning.",
        steps,
        "worker",
    )


def workflow_views(design: EnterpriseDesign) -> list[View]:
    return [
        _flow(
            f"workflow-{workflow.id.removeprefix('workflow-')}",
            workflow.name,
            (workflow.description or "")
            + (" Includes a human approval gate." if workflow.hitl_required else ""),
            workflow.steps,
            "policy" if workflow.hitl_required else "application",
        )
        for workflow in design.workflows
    ]


def guardrail_view(design: EnterpriseDesign) -> View | None:
    if not design.guardrails:
        return None
    order = ["input", "retrieval", "tool", "execution", "output", "audit"]
    steps = []
    for stage in order:
        controls = [c.control for c in design.guardrails if c.stage == stage]
        if controls:
            steps.append(f"{stage.title()}: {controls[0]}")
    for control in design.guardrails:
        if control.stage not in order:
            steps.append(f"{control.stage.title()}: {control.control}")
    return _flow(
        "guardrails",
        "Guardrail stages",
        "Defense layers from input to audit; authorization stays outside prompts.",
        steps,
        "policy",
    )


def fallback_view(design: EnterpriseDesign) -> View | None:
    spec = fallback_sequence(design)
    return _from_spec(spec) if spec else None


def async_view(design: EnterpriseDesign) -> View | None:
    spec = async_sequence(design)
    return _from_spec(spec) if spec else None


def recovery_view(design: EnterpriseDesign) -> View | None:
    if design.requirements.topology != "application-dr" or design.deployment is None:
        return None
    region = design.deployment.region
    groups = [
        (
            "Primary region",
            [
                ("Gateway + compute", region),
                ("Data (primary)", region),
                ("Budget authority", "single writer"),
            ],
            "application",
        ),
        (
            "Recovery region",
            [
                ("Gateway + compute", "warm standby"),
                ("Data (replica)", "async"),
                ("Budget authority", "promoted on failover"),
            ],
            "worker",
        ),
    ]
    scene = group_scene("Recovery topology", groups, "Application disaster recovery", None, None)
    mermaid = (
        "flowchart LR\n"
        '    subgraph primary["Primary region"]\n        p1["Gateway + compute"]\n'
        '        p2[("Data primary")]\n    end\n'
        '    subgraph recovery["Recovery region"]\n        r1["Gateway + compute (warm)"]\n'
        '        r2[("Data replica")]\n    end\n'
        "    p2 -.->|replication| r2\n    p1 -.->|traffic switch runbook| r1\n"
    )
    return View(
        "recovery",
        "Recovery topology",
        "Separate recovery environment; provider failover alone is not application DR.",
        mermaid,
        scene,
    )


def scale_view(design: EnterpriseDesign) -> View | None:
    targets = scale_targets(design)
    if not targets:
        return None
    order = (
        ("http", "Request-scaled", "application"),
        ("queue", "Queue-scaled", "worker"),
        ("managed", "Platform-managed", "ops"),
    )
    groups: list[tuple[str, list[tuple[str, str]], str]] = []
    lines = ["flowchart LR"]
    for mode, title, style in order:
        members = [item for item in targets if item.mode == mode]
        if not members:
            continue
        groups.append((title, [(item.name, item.replicas) for item in members], style))
        lines.append(f'    subgraph {mode}["{mlabel(title)}"]')
        for item in members:
            lines.append(
                f'        {mid(item.service_id)}["{mlabel(item.name)}<br/>{mlabel(item.replicas)}"]'
            )
        lines.append("    end")
    label = f"{design.requirements.profile} | ceiling {replica_ceiling(design)}"
    scene = group_scene("Scale-up architecture", groups, label, None, None)
    return View(
        "scale",
        "Scale-up architecture",
        "How each service scales: request concurrency, queue depth, or platform-managed capacity. "
        "Replica ranges match the generated manifests and are load-test starting points.",
        "\n".join(lines) + "\n",
        scene,
    )


def all_views(design: EnterpriseDesign, graph: ArchitectureGraph) -> list[View]:
    views: list[View | None] = [
        context_view(design),
        architecture_view(design, graph),
        request_view(design),
        *oauth_views(design),
        deployment_view(design),
        data_view(design),
        ingestion_view(design),
        *workflow_views(design),
        budget_view() if design.budget_policy else None,
        fallback_view(design),
        async_view(design),
        guardrail_view(design),
        recovery_view(design),
        scale_view(design),
    ]
    return [view for view in views if view is not None]


COMPONENT_VIEWS: dict[str, tuple[str, ...]] = {
    "system": ("architecture", "request", "scale"),
    "api": ("request",),
    "routing": ("fallback",),
    "budget": ("budget",),
    "workflow": ("workflow-",),
    "rag": ("ingestion",),
    "data": ("data",),
    "infra": ("deployment", "recovery", "scale"),
    "resilience": ("async", "fallback", "recovery", "scale"),
    "auth": ("oauth-",),
    "guard": ("guardrails",),
    "security": ("architecture", "guardrails"),
    "observe": ("architecture",),
    "diagram": ("",),
    "hld": ("context", "architecture", "request", "deployment"),
    "lld": ("",),
}


def views_for(component: str, views: list[View]) -> list[View]:
    prefixes = COMPONENT_VIEWS.get(component, ())
    selected = []
    for prefix in prefixes:
        for view in views:
            matches = view.key == prefix or (prefix.endswith("-") and view.key.startswith(prefix))
            if (prefix == "" or matches) and view not in selected:
                selected.append(view)
    return selected
