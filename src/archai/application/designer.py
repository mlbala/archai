from __future__ import annotations

import copy

from archai.application.registry import COMPONENTS
from archai.domain.cost import estimate_capacity, estimate_cost
from archai.schemas.models import (
    APIContract,
    ArchitectureGraph,
    BudgetPolicy,
    CachePolicy,
    ComponentState,
    ComponentStatus,
    DataStore,
    DecisionLock,
    DeploymentProfile,
    Edge,
    EnterpriseDesign,
    GuardrailControl,
    IdentityPolicy,
    ModelAlias,
    Node,
    ObservabilityPlan,
    QueuePolicy,
    RequirementsSpec,
    Risk,
    Service,
    TargetEndpoint,
    Workflow,
)


def _endpoint(provider: str, requirements: RequirementsSpec, index: int) -> TargetEndpoint:
    return TargetEndpoint(
        id=f"endpoint-{provider.lower().replace(' ', '-')}-{index}",
        provider=provider,
        deployment_id=f"USER_SUPPLIED_{provider.upper().replace(' ', '_')}_DEPLOYMENT",
        region=requirements.data_residency[0],
        modalities=["text"],
        supports_tools="agent" in " ".join(requirements.archetypes).lower(),
        supports_schema=True,
        context_limit=128_000,
        input_price_per_million=None,
        output_price_per_million=None,
        rpm=max(60, int(requirements.peak_rps * 60 * requirements.model_calls_per_request)),
        tpm=max(
            10_000,
            int(
                requirements.peak_rps
                * 60
                * requirements.model_calls_per_request
                * (requirements.input_tokens + requirements.output_tokens)
            ),
        ),
    )


def new_design(project: str, requirements: RequirementsSpec) -> EnterpriseDesign:
    return EnterpriseDesign(project=project, requirements=requirements)


def apply_scope(
    baseline: EnterpriseDesign | None,
    project: str,
    requirements: RequirementsSpec,
    scope: list[str],
    locks: list[DecisionLock],
) -> EnterpriseDesign:
    design = copy.deepcopy(baseline) if baseline else new_design(project, requirements)
    design.requirements = requirements
    locked_components = {lock.component for lock in locks}
    for component in scope:
        if component in locked_components and baseline is not None:
            continue
        _apply_component(design, component)
        design.components[component] = ComponentState(name=component, status=ComponentStatus.valid)
    for component in scope:
        for downstream in COMPONENTS[component].invalidates:
            if downstream in scope:
                continue
            state = design.components.get(downstream)
            if state and state.status == ComponentStatus.valid:
                state.status = ComponentStatus.stale
                state.reason = f"invalidated by {component}"
    return design


def _apply_component(design: EnterpriseDesign, name: str) -> None:
    req = design.requirements
    if name == "requirements":
        return
    if name == "system":
        design.services = [
            Service(
                id="svc-ingress",
                name="Enterprise API gateway",
                kind="gateway",
                region=req.region,
                owner="platform",
            ),
            Service(
                id="svc-app",
                name="Application orchestration",
                kind="application",
                region=req.region,
                owner="application",
            ),
            Service(
                id="svc-admission",
                name="Model admission",
                kind="policy",
                region=req.region,
                owner="ai-platform",
            ),
            Service(
                id="svc-ai-gateway",
                name="Managed AI gateway",
                kind="ai-gateway",
                region=req.region,
                owner="ai-platform",
            ),
            Service(
                id="svc-observe",
                name="Telemetry pipeline",
                kind="operations",
                region=req.region,
                owner="operations",
            ),
        ]
    elif name == "api":
        design.api_contracts = [
            APIContract(
                id="api-chat",
                path="/v1/chat",
                method="POST",
                auth="OIDC bearer token",
                streaming=True,
            ),
            APIContract(id="api-jobs", path="/v1/jobs", method="POST", auth="OIDC bearer token"),
            APIContract(
                id="api-job-status",
                path="/v1/jobs/{job_id}",
                method="GET",
                auth="OIDC bearer token",
            ),
        ]
    elif name == "routing":
        design.endpoints = [
            _endpoint(provider, req, index)
            for index, provider in enumerate(req.allowed_target_providers, start=1)
        ]
        design.model_aliases = [
            ModelAlias(
                id="enterprise-chat",
                task="enterprise conversational response",
                endpoint_ids=[endpoint.id for endpoint in design.endpoints],
            )
        ]
    elif name == "budget":
        design.budget_policy = BudgetPolicy(
            currency=req.currency, monthly_limit=req.monthly_budget, hard_limit=True
        )
    elif name == "cache":
        design.cache_policy = CachePolicy(
            exact_enabled=True,
            semantic_enabled=False,
            namespace_fields=[
                "tenant",
                "principal_scope",
                "index_version",
                "prompt_version",
                "route_policy_version",
                "locale",
            ],
            ttl_seconds=300,
        )
    elif name == "workflow":
        design.workflows = [
            Workflow(
                id="workflow-interactive",
                name="Interactive managed-model request",
                steps=["authorize", "retrieve", "reserve", "route", "validate", "settle"],
                hitl_required=req.tool_side_effects == "approval",
            )
        ]
    elif name in {"rag", "data"}:
        vector_kind = (
            "Azure AI Search" if req.profile.startswith("azure") else "managed vector service"
        )
        if req.profile == "aws-eks":
            vector_kind = "Amazon OpenSearch Serverless"
        design.data_stores = [
            DataStore(
                id="store-ledger",
                name="Budget ledger",
                kind="PostgreSQL",
                purpose="transactional reservations and settlement",
                region=req.region,
                partition_key="organization_id",
                consistency="serializable transaction",
                retention_days=2555,
            ),
            DataStore(
                id="store-object",
                name="Object storage",
                kind="Blob Storage" if req.profile.startswith("azure") else "S3",
                purpose="source documents by immutable object reference",
                region=req.region,
                partition_key="tenant_id",
                consistency="read-after-write",
                retention_days=365,
            ),
            DataStore(
                id="store-vector",
                name="Retrieval index",
                kind=vector_kind,
                purpose="ACL-filtered hybrid retrieval; embedding/index version bound",
                region=req.region,
                partition_key="tenant_id",
                consistency="eventual with versioned index",
                retention_days=365,
            ),
        ]
    elif name == "infra":
        profiles = {
            "azure-aca": (
                "azure",
                [
                    "API Management",
                    "Container Apps",
                    "Service Bus",
                    "PostgreSQL",
                    "Blob Storage",
                    "Key Vault",
                    "Azure Monitor",
                ],
            ),
            "azure-aks": (
                "azure",
                [
                    "API Management",
                    "AKS",
                    "Service Bus",
                    "KEDA",
                    "PostgreSQL",
                    "Blob Storage",
                    "Key Vault",
                    "Azure Monitor",
                ],
            ),
            "aws-eks": (
                "aws",
                [
                    "API Gateway/ALB",
                    "EKS",
                    "SQS",
                    "RDS PostgreSQL",
                    "S3",
                    "Secrets Manager",
                    "CloudWatch",
                ],
            ),
            "agnostic": (
                "agnostic",
                [
                    "enterprise gateway",
                    "managed containers",
                    "managed broker",
                    "transactional database",
                    "object storage",
                    "secret manager",
                    "telemetry",
                ],
            ),
        }
        cloud, resources = profiles[req.profile]
        design.deployment = DeploymentProfile(
            name=req.profile, hosting_cloud=cloud, region=req.region, resources=resources
        )
    elif name == "resilience":
        broker = "Azure Service Bus" if req.profile.startswith("azure") else "AWS SQS"
        if req.profile == "agnostic":
            broker = "validated managed broker"
        design.queue_policy = QueuePolicy(
            broker=broker, max_attempts=5, max_age_seconds=3600, dlq_owner="operations"
        )
    elif name == "auth":
        design.identity_policy = IdentityPolicy(
            idp="Entra ID",
            tenant_mode=req.tenant_isolation,
            required_claims=["iss", "aud", "exp", "tid", "sub", "roles"],
            object_level_authorization=True,
        )
    elif name == "guard":
        design.guardrails = [
            GuardrailControl(
                id="guard-input",
                stage="input",
                control="size, content, and task authorization",
                owner="application",
                enforcement="custom-runtime-required",
            ),
            GuardrailControl(
                id="guard-retrieval",
                stage="retrieval",
                control="tenant and object ACL filter",
                owner="application",
                enforcement="custom-runtime-required",
            ),
            GuardrailControl(
                id="guard-tools",
                stage="tool",
                control="schema, authorization, and exact-argument approval",
                owner="workflow",
                enforcement="custom-runtime-required",
            ),
            GuardrailControl(
                id="guard-output",
                stage="output",
                control="schema and sensitive-data release validation",
                owner="application",
                enforcement="custom-runtime-required",
            ),
        ]
    elif name == "security":
        design.risks = [
            Risk(
                id="risk-injection",
                title="Untrusted content influences model or tool behavior",
                severity="high",
                mitigation="Treat content as data; enforce authorization outside prompts and validate tool arguments",
                owner="security",
            ),
            Risk(
                id="risk-usage",
                title="Unresolved provider usage may exceed reported spend",
                severity="high",
                mitigation="Retain dispatched reservations until reconciliation",
                owner="finops",
            ),
        ]
    elif name == "observe":
        design.observability = ObservabilityPlan(
            tracing="OpenTelemetry",
            model_analytics="Langfuse",
            correlation_ids=[
                "logical_request_id",
                "attempt_id",
                "reservation_id",
                "queue_job_id",
                "tool_call_id",
                "approval_id",
            ],
            redaction_required=True,
        )
    elif name == "eval":
        if not any(risk.id == "risk-evaluation" for risk in design.risks):
            design.risks.append(
                Risk(
                    id="risk-evaluation",
                    title="Fallback route quality regression",
                    severity="medium",
                    mitigation="Evaluate task quality, safety, latency, and cost for every eligible route",
                    owner="ai-quality",
                )
            )
    elif name == "cost":
        design.capacity = estimate_capacity(req)
        if design.endpoints:
            design.costs = [estimate_cost(req, design.endpoints[0])]
        else:
            design.costs = []
    elif name in {"diagram", "doc"}:
        return


def build_graph(design: EnterpriseDesign) -> ArchitectureGraph:
    nodes = [
        Node(id="client", label="Enterprise client", kind="client", lane="clients/identity"),
        Node(
            id="identity",
            label=design.identity_policy.idp if design.identity_policy else "External IdP",
            kind="identity",
            lane="clients/identity",
        ),
    ]
    nodes.extend(
        Node(id=service.id, label=service.name, kind=service.kind, lane=_lane(service.kind))
        for service in design.services
    )
    nodes.extend(
        Node(id=store.id, label=store.name, kind="data", lane="data/queues/workers")
        for store in design.data_stores
    )
    nodes.extend(
        Node(
            id=endpoint.id,
            label=f"{endpoint.provider} managed endpoint",
            kind="managed-model",
            lane="managed providers",
        )
        for endpoint in design.endpoints
    )
    node_ids = {node.id for node in nodes}
    edges: list[Edge] = []

    def add(edge_id: str, source: str, target: str, label: str, kind: str = "data") -> None:
        if source in node_ids and target in node_ids:
            edges.append(Edge(id=edge_id, source=source, target=target, label=label, kind=kind))

    add("edge-signin", "client", "identity", "sign in", "identity")
    add("edge-ingress", "client", "svc-ingress", "OIDC token + request")
    add("edge-auth", "identity", "svc-ingress", "token trust", "identity")
    add("edge-app", "svc-ingress", "svc-app", "authorized request")
    add("edge-admission", "svc-app", "svc-admission", "bounded model request")
    add("edge-router", "svc-admission", "svc-ai-gateway", "eligible route + reservation")
    for index, endpoint in enumerate(design.endpoints, start=1):
        add(f"edge-provider-{index}", "svc-ai-gateway", endpoint.id, "managed API call")
    for index, store in enumerate(design.data_stores, start=1):
        add(f"edge-data-{index}", "svc-app", store.id, store.purpose)
    add("edge-telemetry", "svc-app", "svc-observe", "redacted telemetry", "telemetry")
    return ArchitectureGraph(nodes=nodes, edges=edges)


def _lane(kind: str) -> str:
    return {
        "gateway": "enterprise ingress",
        "application": "application/workflows",
        "policy": "application/workflows",
        "ai-gateway": "AI gateway",
        "operations": "security/operations",
    }.get(kind, "application/workflows")
