"""Deterministic baseline design and canonical graph projection.

The baseline is used when no architect model is configured, when a role fails, and as the scaffold
that model proposals are merged onto. It derives every choice from requirements and profile.
"""

from __future__ import annotations

import copy
from decimal import ROUND_HALF_UP, Decimal

from archai.application.registry import COMPILED_COMPONENTS, COMPONENTS
from archai.domain.cost import estimate_capacity, estimate_cost
from archai.domain.geography import endpoint_region, geography
from archai.schemas.models import (
    APIContract,
    ArchitectureDecision,
    ArchitectureGraph,
    BudgetAllocation,
    BudgetPolicy,
    CachePolicy,
    CloudResource,
    ComponentState,
    ComponentStatus,
    DataStore,
    DecisionLock,
    DeploymentProfile,
    Edge,
    EnterpriseDesign,
    EvalMetric,
    EvalPlan,
    GuardrailControl,
    IdentityPolicy,
    MetricSpec,
    ModelAlias,
    Node,
    OAuthFlow,
    ObservabilityPlan,
    QueuePolicy,
    RAGPipeline,
    RequirementsSpec,
    ResiliencePlan,
    Risk,
    RoleDefinition,
    RoutingPolicy,
    Service,
    ServiceIdentity,
    TargetEndpoint,
    Threat,
    Workflow,
)

BASELINE_SOURCE = "deterministic-baseline"
REQUIRED_CLAIMS = ["iss", "aud", "exp", "nbf", "tid", "sub", "roles", "scp"]
REQUIRED_CACHE_NAMESPACE = [
    "tenant",
    "principal_scope",
    "index_version",
    "prompt_version",
    "route_policy_version",
    "locale",
]
REQUIRED_CORRELATION_IDS = [
    "logical_request_id",
    "attempt_id",
    "reservation_id",
    "queue_job_id",
    "tool_call_id",
    "approval_id",
]

LANES = (
    "Clients & identity",
    "Enterprise ingress",
    "Application & workflows",
    "Data, queues & workers",
    "AI gateway & managed models",
    "Security & operations",
)


# ---------------------------------------------------------------- requirement predicates


def has_rag(req: RequirementsSpec) -> bool:
    text = " ".join(req.archetypes).lower()
    return bool(req.data_sources) or any(
        word in text for word in ("rag", "retriev", "knowledge", "search", "document")
    )


def uses_tools(req: RequirementsSpec) -> bool:
    text = " ".join(req.archetypes).lower()
    return (
        "agent" in text
        or "tool" in text
        or "sql" in text
        or bool(req.integrations)
        or (req.tool_side_effects != "forbidden" and "copilot" in text)
    )


def needs_async_jobs(req: RequirementsSpec) -> bool:
    if uses_tools(req):
        return True
    users = {item.lower() for item in req.users}
    if users & {"scheduler", "batch"}:
        return True
    text = " ".join(req.archetypes).lower()
    return any(word in text for word in ("classification", "extraction", "batch", "pipeline"))


def needs_queue(req: RequirementsSpec) -> bool:
    return has_rag(req) or needs_async_jobs(req)


def auth_scheme(req: RequirementsSpec) -> str:
    return f"OIDC bearer token ({req.identity_provider or 'Entra ID'})"


def cloud_of(profile: str) -> str:
    if profile.startswith("azure"):
        return "azure"
    if profile.startswith("aws"):
        return "aws"
    return "agnostic"


def _pick(profile: str, azure: str, aws: str, agnostic: str) -> str:
    return {"azure": azure, "aws": aws}.get(cloud_of(profile), agnostic)


def slug_id(value: str, prefix: str) -> str:
    cleaned = "".join(char if char.isalnum() else "-" for char in value.lower()).strip("-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    cleaned = cleaned[:48].strip("-") or "item"
    return cleaned if cleaned.startswith(prefix) else f"{prefix}{cleaned}"


# ---------------------------------------------------------------- endpoints


def _endpoint(provider: str, requirements: RequirementsSpec, index: int) -> TargetEndpoint:
    return TargetEndpoint(
        id=f"endpoint-{provider.lower().replace(' ', '-')}-{index}",
        provider=provider,
        deployment_id=f"USER_SUPPLIED_{provider.upper().replace(' ', '_')}_DEPLOYMENT",
        region=endpoint_region(provider, requirements.data_residency),
        modalities=["text"],
        supports_tools=uses_tools(requirements),
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


def _embedding_endpoint(provider: str, requirements: RequirementsSpec) -> TargetEndpoint:
    base = provider.lower().replace(" ", "-")
    return TargetEndpoint(
        id=f"endpoint-{base}-embedding",
        provider=provider,
        deployment_id=f"USER_SUPPLIED_{provider.upper().replace(' ', '_')}_EMBEDDING_DEPLOYMENT",
        region=endpoint_region(provider, requirements.data_residency),
        modalities=["embeddings"],
        supports_tools=False,
        supports_schema=False,
        context_limit=8_000,
        rpm=600,
        tpm=max(100_000, (requirements.documents_per_day or 500) * 2_000 // 60),
    )


def target_endpoints(req: RequirementsSpec) -> list[TargetEndpoint]:
    endpoints = [
        _endpoint(provider, req, index)
        for index, provider in enumerate(req.allowed_target_providers, start=1)
    ]
    if has_rag(req) and req.allowed_target_providers:
        endpoints.append(_embedding_endpoint(req.allowed_target_providers[0], req))
    return endpoints


def chat_endpoints(design: EnterpriseDesign) -> list[TargetEndpoint]:
    return [item for item in design.endpoints if "embeddings" not in item.modalities]


# ---------------------------------------------------------------- scope application


def new_design(project: str, requirements: RequirementsSpec) -> EnterpriseDesign:
    return EnterpriseDesign(project=project, requirements=requirements)


_EXCLUSION_REASONS = {
    "cache": "Response caching is not required for this application",
    "auth": "User RBAC is not required for this application",
    "infra": "Cloud deployment is not required for this application",
    "rag": "Retrieval is not required for this application",
    "observe": "Observability is not required for this application",
    "eval": "Evaluation is not required for this application",
    "workflow": "Workflows are not required for this application",
    "guard": "Guardrails are not required for this application",
    "resilience": "Resilience planning is not required for this application",
}


def not_applicable_reason(component: str, req: RequirementsSpec) -> str | None:
    from archai.interview.exclusions import effective_exclusions

    if component in effective_exclusions(req.model_dump(mode="json")):
        return _EXCLUSION_REASONS.get(component, "Excluded in the requirements")
    if component == "rag" and not has_rag(req):
        return "No retrieval archetype or knowledge sources in the requirements"
    return None


def apply_scope(
    baseline: EnterpriseDesign | None,
    project: str,
    requirements: RequirementsSpec,
    scope: list[str],
    locks: list[DecisionLock],
) -> EnterpriseDesign:
    design = copy.deepcopy(baseline) if baseline else new_design(project, requirements)
    design.requirements = requirements
    locked_components = {lock.component for lock in locks if lock.field_path is None}
    for component in scope:
        if component not in COMPONENTS:
            continue
        if component in locked_components and baseline is not None:
            continue
        reason = not_applicable_reason(component, requirements)
        if reason:
            _clear_component(design, component)
            design.components[component] = ComponentState(
                name=component,
                status=ComponentStatus.not_applicable,
                reason=reason,
                source=BASELINE_SOURCE,
            )
            continue
        baseline_component(design, component)
        design.components[component] = ComponentState(
            name=component, status=ComponentStatus.valid, source=BASELINE_SOURCE
        )
    for component in scope:
        if component not in COMPONENTS:
            continue
        for downstream in COMPONENTS[component].invalidates:
            if downstream in scope:
                continue
            state = design.components.get(downstream)
            if state and state.status == ComponentStatus.valid:
                state.status = ComponentStatus.stale
                state.reason = f"invalidated by {component}"
    return design


def _clear_component(design: EnterpriseDesign, component: str) -> None:
    replace_component_decisions(design, component)
    if component == "cache":
        design.cache_policy = None
    elif component == "auth":
        design.identity_policy = None
    elif component == "infra":
        design.deployment = None
    elif component == "rag":
        design.rag_pipeline = None
    elif component == "workflow":
        design.workflows = []
    elif component == "guard":
        design.guardrails = []
    elif component == "observe":
        design.observability = None
    elif component == "eval":
        design.eval_plan = None
    elif component == "resilience":
        design.queue_policy = None
        design.resilience = None


def add_decision(
    design: EnterpriseDesign,
    component: str,
    title: str,
    decision: str,
    rationale: str,
    alternatives: list[str] | None = None,
    consequences: str | None = None,
    source: str = BASELINE_SOURCE,
) -> None:
    identifier = slug_id(f"{component}-{title}", "adr-")
    design.decisions = [item for item in design.decisions if item.id != identifier]
    design.decisions.append(
        ArchitectureDecision(
            id=identifier,
            component=component,
            title=title,
            decision=decision,
            rationale=rationale,
            alternatives=alternatives or [],
            consequences=consequences,
            source=source,
        )
    )


def replace_component_decisions(design: EnterpriseDesign, component: str) -> None:
    design.decisions = [item for item in design.decisions if item.component != component]


def baseline_component(design: EnterpriseDesign, name: str) -> None:
    req = design.requirements
    if name in COMPONENTS and name not in {"cost", "requirements", *COMPILED_COMPONENTS}:
        replace_component_decisions(design, name)
    builder = _BUILDERS.get(name)
    if builder is not None:
        builder(design, req)


# ---------------------------------------------------------------- component builders


def _system(design: EnterpriseDesign, req: RequirementsSpec) -> None:
    rag = has_rag(req)
    tools = uses_tools(req)
    jobs = needs_async_jobs(req)
    gateway = _pick(req.profile, "Azure API Management", "Amazon API Gateway + ALB", "Kong/APISIX")
    compute = _pick(
        req.profile,
        "Azure Container Apps" if req.profile == "azure-aca" else "AKS deployment",
        "EKS deployment",
        "managed containers",
    )
    app_dependencies = ["svc-admission", "store-state"]
    if rag:
        app_dependencies.append("svc-retrieval")
    if tools:
        app_dependencies.append("svc-tools")
    services = [
        Service(
            id="svc-ingress",
            name="Enterprise API gateway",
            kind="gateway",
            region=req.region,
            owner="platform",
            technology=gateway,
            scaling="managed gateway units sized for peak RPS",
            responsibilities=[
                "Validate OIDC access tokens (issuer, audience, signature, expiry, tenant)",
                "Per-principal request-rate limits and payload size limits",
                "Correlation ID injection and external API versioning",
            ],
            exposes=["/v1/*"],
            depends_on=["svc-app"],
        ),
        Service(
            id="svc-app",
            name="Application API and orchestration",
            kind="application",
            region=req.region,
            owner="application",
            technology=f"Python/FastAPI on {compute}",
            scaling="HTTP concurrency autoscaling; stateless replicas",
            responsibilities=_app_responsibilities(rag, tools, jobs),
            exposes=_app_exposes(rag, jobs),
            depends_on=app_dependencies,
            data_owned=["store-state"],
        ),
        Service(
            id="svc-admission",
            name="Model admission and budget service",
            kind="policy",
            region=req.region,
            owner="ai-platform",
            technology=f"Python service on {compute}",
            scaling="horizontal; ledger transactions are the serialization point",
            responsibilities=[
                "Filter eligible model routes by residency, capability, quota, and health",
                "Reserve budget atomically across organization/department/application scopes",
                "Settle actual usage and keep unresolved liabilities for reconciliation",
            ],
            depends_on=["svc-ai-gateway", "store-ledger"],
            data_owned=["store-ledger"],
        ),
        Service(
            id="svc-ai-gateway",
            name="AI gateway (LiteLLM)",
            kind="ai-gateway",
            region=req.region,
            owner="ai-platform",
            technology=f"LiteLLM proxy on {compute}",
            scaling="horizontal; provider quotas bound throughput",
            responsibilities=[
                "Adapt requests to managed provider APIs via logical model aliases",
                "Own provider retries, timeouts, and approved fallback (single retry owner)",
                "Emit per-attempt usage and latency telemetry",
            ],
        ),
    ]
    if rag:
        services.append(
            Service(
                id="svc-retrieval",
                name="Retrieval service",
                kind="retrieval",
                region=req.region,
                owner="application",
                technology="Python service with hybrid search client",
                scaling="horizontal; bounded by search service units",
                responsibilities=[
                    "ACL- and tenant-filtered hybrid retrieval",
                    "Query rewriting and reranking within token ceilings",
                    "Return citations bound to the index version",
                ],
                depends_on=["store-vector", "svc-admission"],
            )
        )
        services.append(
            Service(
                id="svc-ingestion",
                name="Document ingestion worker",
                kind="ingestion",
                region=req.region,
                owner="data-platform",
                technology="Python worker with isolated document parsers",
                scaling="queue-length autoscaling bounded by embedding quota",
                responsibilities=[
                    "Parse documents in an isolated sandbox with size limits",
                    "Chunk, embed, and index with ACL metadata and index version",
                    "Propagate deletions and permission changes to the index",
                ],
                depends_on=["store-object", "store-vector", "svc-admission"],
            )
        )
    if tools:
        services.append(
            Service(
                id="svc-tools",
                name="Tool execution service",
                kind="tool-executor",
                region=req.region,
                owner="application",
                technology="Python service with per-tool adapters",
                scaling="horizontal with per-tool concurrency limits",
                responsibilities=[
                    "Validate tool arguments against schemas and caller permissions",
                    "Require human approval bound to exact operation and arguments"
                    if req.tool_side_effects == "approval"
                    else "Enforce read-only tool permissions"
                    if req.tool_side_effects == "forbidden"
                    else "Execute authorized actions with idempotency keys",
                    "Record auditable tool calls; never replay uncertain side effects",
                ],
                depends_on=["store-state"],
            )
        )
    if jobs:
        services.append(
            Service(
                id="svc-worker",
                name="Asynchronous job worker",
                kind="worker",
                region=req.region,
                owner="application",
                technology=f"Python worker on {compute}",
                scaling="queue-based autoscaling within downstream quota",
                responsibilities=[
                    "Process long-running workflows, batch evaluation, and exports",
                    "Idempotent state transitions with deduplication keys",
                ],
                depends_on=["svc-admission", "store-state"],
            )
        )
    services.append(
        Service(
            id="svc-observe",
            name="Telemetry pipeline",
            kind="operations",
            region=req.region,
            owner="operations",
            technology=_pick(
                req.profile,
                "OpenTelemetry Collector → Azure Monitor + Langfuse",
                "OpenTelemetry Collector → CloudWatch + Langfuse",
                "OpenTelemetry Collector + Langfuse",
            ),
            scaling="managed",
            responsibilities=[
                "Collect correlated traces, metrics, and redacted logs",
                "Model-call analytics and evaluation traces",
            ],
        )
    )
    design.services = services
    add_decision(
        design,
        "system",
        "Modular services behind one enterprise gateway and one AI gateway",
        "Split ingress, orchestration, model admission, AI gateway"
        + (", retrieval/ingestion" if rag else "")
        + (", and tool execution" if tools else "")
        + (", and a jobs worker" if jobs else "")
        + " into independently scaled services.",
        "Each control (authentication, budget, provider retry, tool authorization) gets exactly "
        "one owner, avoiding duplicate retries and conflicting policies.",
        ["Single monolithic API", "Direct provider calls from the application"],
        "More deployable units; requires service-to-service identity and tracing.",
    )


def _app_responsibilities(rag: bool, tools: bool, jobs: bool) -> list[str]:
    items = [
        "Derive tenant, user, and department from trusted claims",
        "Conversation context, prompt templates, and streaming responses",
    ]
    if tools and rag:
        items.append("Coordinate retrieval, tool calls, and human approval gates")
    elif tools:
        items.append("Coordinate tool calls and human approval gates")
    elif rag:
        items.append("Coordinate retrieval and grounded responses")
    if jobs:
        items.append("Publish asynchronous jobs through a transactional outbox")
    return items


def _app_exposes(rag: bool, jobs: bool) -> list[str]:
    items = ["chat", "conversations"]
    if jobs:
        items.append("jobs")
    if rag:
        items.append("documents")
    items.append("feedback")
    return items


def _state_purpose(req: RequirementsSpec) -> str:
    parts = ["conversations"]
    if needs_async_jobs(req):
        parts.append("jobs")
        parts.append("outbox")
    elif needs_queue(req):
        parts.append("outbox")
    if uses_tools(req) and req.tool_side_effects == "approval":
        parts.append("approvals")
    return ", ".join(parts)


def _api(design: EnterpriseDesign, req: RequirementsSpec) -> None:
    peak_rpm = max(60, int(req.peak_rps * 60))
    auth = auth_scheme(req)
    contracts = [
        APIContract(
            id="api-chat",
            path="/v1/chat",
            method="POST",
            auth=auth,
            streaming=True,
            summary="Send a user message and stream a grounded answer (server-sent events)",
            service_id="svc-app",
            scopes=["chat.invoke"],
            rate_limit_rpm=peak_rpm,
            request_fields=["conversation_id", "message", "attachments[]", "locale"],
            response_fields=["event stream: token, citation, tool_proposal, done", "usage"],
        ),
        APIContract(
            id="api-conversation",
            path="/v1/conversations/{conversation_id}",
            method="GET",
            auth=auth,
            summary="Read a conversation the caller is authorized to see",
            service_id="svc-app",
            scopes=["chat.read"],
            rate_limit_rpm=peak_rpm,
            request_fields=["conversation_id"],
            response_fields=["messages[]", "citations[]", "created_at"],
        ),
    ]
    if needs_async_jobs(req):
        contracts += [
            APIContract(
                id="api-jobs",
                path="/v1/jobs",
                method="POST",
                auth=auth,
                summary="Submit a long-running job; returns 202 with a job ID",
                service_id="svc-app",
                scopes=["jobs.submit"],
                rate_limit_rpm=max(30, peak_rpm // 4),
                request_fields=["job_type", "input_ref", "idempotency_key"],
                response_fields=["job_id", "status_url"],
            ),
            APIContract(
                id="api-job-status",
                path="/v1/jobs/{job_id}",
                method="GET",
                auth=auth,
                summary="Read job status and result references (object-level authorized)",
                service_id="svc-app",
                scopes=["jobs.read"],
                rate_limit_rpm=peak_rpm,
                request_fields=["job_id"],
                response_fields=["status", "result_ref", "error"],
            ),
        ]
    if has_rag(req):
        contracts.append(
            APIContract(
                id="api-documents",
                path="/v1/documents",
                method="POST",
                auth=auth,
                summary="Register a document for ingestion with ACL metadata",
                service_id="svc-app",
                scopes=["documents.write"],
                rate_limit_rpm=max(30, peak_rpm // 4),
                request_fields=["source_uri", "acl", "classification"],
                response_fields=["document_id", "job_id"],
            )
        )
    if uses_tools(req) and req.tool_side_effects == "approval":
        contracts.append(
            APIContract(
                id="api-approval",
                path="/v1/approvals/{approval_id}/decision",
                method="POST",
                auth=auth,
                summary="Approve or reject an exact pending tool action",
                service_id="svc-app",
                scopes=["approvals.decide"],
                rate_limit_rpm=120,
                request_fields=["approval_id", "decision", "arguments_hash", "comment"],
                response_fields=["status", "executed_at"],
            )
        )
    contracts.append(
        APIContract(
            id="api-feedback",
            path="/v1/feedback",
            method="POST",
            auth=auth,
            summary="Record answer feedback for evaluation datasets",
            service_id="svc-app",
            scopes=["feedback.write"],
            rate_limit_rpm=peak_rpm,
            request_fields=["conversation_id", "message_id", "rating", "comment"],
            response_fields=["accepted"],
        )
    )
    design.api_contracts = contracts
    add_decision(
        design,
        "api",
        "Versioned REST API with SSE streaming",
        "Expose /v1 REST resources through the enterprise gateway; stream chat with SSE.",
        "SSE passes through API gateways without protocol upgrades and supports interruption "
        "reporting without transparent replay.",
        ["WebSockets", "gRPC"],
    )


def _routing(design: EnterpriseDesign, req: RequirementsSpec) -> None:
    design.endpoints = target_endpoints(req)
    chat = chat_endpoints(design)
    fallback = [item.id for item in chat[1:]] if req.topology != "single-cloud" else []
    aliases = [
        ModelAlias(
            id="enterprise-chat",
            task="enterprise conversational response",
            endpoint_ids=[item.id for item in (chat if fallback else chat[:1])],
            required_capabilities=["text", "streaming", "json-schema"]
            + (["tools"] if uses_tools(req) else []),
            max_output_tokens=max(req.output_tokens * 2, 1024),
            fallback_endpoint_ids=fallback,
            quality_gate="Pass the task evaluation suite for this route before enabling it",
        )
    ]
    embedding = [item for item in design.endpoints if "embeddings" in item.modalities]
    if embedding:
        aliases.append(
            ModelAlias(
                id="enterprise-embedding",
                task="document and query embeddings for one index version",
                endpoint_ids=[embedding[0].id],
                required_capabilities=["embeddings"],
                quality_gate="Index version must match the embedding deployment and dimensions",
            )
        )
    design.model_aliases = aliases
    design.routing_policy = RoutingPolicy(
        eligibility_rules=[
            f"Processing and storage geography within {', '.join(req.data_residency)}"
            + (
                f" (geography {geography(req.data_residency[0])}; cross-region inference "
                "profiles must keep every destination inside it)"
                if geography(req.data_residency[0])
                else ""
            ),
            f"Tenant isolation mode '{req.tenant_isolation}' and data classification policy",
            "Modality, context, output limit, tool and schema support match the alias",
            "Evaluation threshold passed for the task",
            "Allocated quota headroom, health, and request deadline",
        ],
        max_attempts=2,
    )
    add_decision(
        design,
        "routing",
        "Logical model aliases with policy-filtered fallback",
        "Applications call task aliases; the admission service filters eligible endpoints before "
        "ranking, and the AI gateway is the only provider-retry owner.",
        "Decouples application code from deployments and keeps fallback inside residency, "
        "capability, and budget policy.",
        ["Hard-coded model names", "Client-side provider SDK retries"],
        "Embedding aliases never fall back across vector spaces.",
    )


def _budget(design: EnterpriseDesign, req: RequirementsSpec) -> None:
    groups = [item for item in req.users if item.strip()][:6] or ["application"]
    reserve = Decimal("10")
    share = ((Decimal(100) - reserve) / len(groups)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    allocations = [
        BudgetAllocation(scope=f"department:{group}", share_percent=share, amount=Decimal(0))
        for group in groups
    ]
    allocations.append(
        BudgetAllocation(scope="platform-reserve", share_percent=reserve, amount=Decimal(0))
    )
    design.budget_policy = BudgetPolicy(
        currency=req.currency,
        monthly_limit=req.monthly_budget,
        hard_limit=True,
        allocations=allocations,
        soft_limit_percent=80,
        per_request_token_ceiling=(req.input_tokens + req.output_tokens) * 4,
        per_workflow_step_ceiling=12,
        rationale="Equal departmental shares with a platform reserve; adjust to business owners.",
    )
    compute_allocations(design.budget_policy)
    add_decision(
        design,
        "budget",
        "Durable reservation ledger for hard budgets",
        "Reserve a bounded per-attempt maximum in a transactional ledger before dispatch and "
        "settle with reported usage; Redis may cache counters but is not the ledger.",
        "Hard monetary limits need atomic checks across hierarchy scopes and must survive "
        "crashes; uncertain dispatches remain liabilities until reconciled.",
        ["Gateway-only token counters", "Monthly invoice review"],
    )


def compute_allocations(policy: BudgetPolicy) -> None:
    total = sum((item.share_percent for item in policy.allocations), Decimal(0))
    if total > 100 and total > 0:
        for item in policy.allocations:
            item.share_percent = (item.share_percent * 100 / total).quantize(Decimal("0.01"))
    for item in policy.allocations:
        item.amount = (policy.monthly_limit * item.share_percent / 100).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )


def _cache(design: EnterpriseDesign, req: RequirementsSpec) -> None:
    design.cache_policy = CachePolicy(
        exact_enabled=True,
        semantic_enabled=False,
        namespace_fields=list(REQUIRED_CACHE_NAMESPACE),
        ttl_seconds=300,
        provider_prompt_caching=True,
        retrieval_cache_ttl_seconds=120 if has_rag(req) else None,
        bypass_conditions=[
            "Requests that propose or execute tool side effects",
            "Personal or restricted data in the prompt or answer",
            "Time-sensitive questions (balances, status, prices)",
        ],
        invalidation_events=[
            "Permission or group membership change",
            "Index version or document deletion",
            "Prompt template or routing policy version change",
        ],
        rationale="Exact caching is safe with full namespace binding; semantic caching stays "
        "opt-in per route until evaluated.",
    )
    add_decision(
        design,
        "cache",
        "Semantic response caching is opt-in",
        "Enable provider prompt caching and namespace-bound exact caching; keep semantic caching "
        "disabled until a route passes correctness evaluation.",
        "Semantic hits can leak answers across permission scopes or return stale facts.",
        ["Global semantic cache"],
    )


def _workflow(design: EnterpriseDesign, req: RequirementsSpec) -> None:
    steps = ["authenticate", "authorize task"]
    if has_rag(req):
        steps.append("retrieve permitted context")
    steps += ["reserve budget", "route to eligible model", "validate output", "settle usage"]
    workflows = [
        Workflow(
            id="workflow-interactive",
            name="Interactive managed-model request",
            trigger="POST /v1/chat",
            description="Synchronous streaming path for user conversations.",
            steps=steps,
            hitl_required=False,
        )
    ]
    if uses_tools(req):
        hitl = req.tool_side_effects == "approval"
        workflows.append(
            Workflow(
                id="workflow-tool-action",
                name="Tool action" + (" with human approval" if hitl else ""),
                trigger="model proposes a tool call",
                description="Tool proposals are validated against schema and permissions"
                + ("; a human approves the exact arguments before execution." if hitl else "."),
                steps=[
                    "validate tool arguments",
                    "check caller permission",
                    *(["request approval bound to arguments hash"] if hitl else []),
                    *(["wait for approver decision"] if hitl else []),
                    "execute with idempotency key",
                    "record audit event",
                ],
                hitl_required=hitl,
            )
        )
    if has_rag(req):
        workflows.append(
            Workflow(
                id="workflow-ingestion",
                name="Document ingestion",
                trigger="POST /v1/documents or connector schedule",
                description="Asynchronous outbox → queue → bounded worker path.",
                steps=[
                    "persist job + outbox",
                    "publish reference message",
                    "parse in sandbox",
                    "chunk and embed",
                    "index with ACL metadata",
                    "update job status",
                ],
                hitl_required=False,
            )
        )
    design.workflows = workflows


def _rag(design: EnterpriseDesign, req: RequirementsSpec) -> None:
    design.rag_pipeline = RAGPipeline(
        ingestion_steps=[
            "Connector sync or upload registers the document with ACL and classification",
            "Isolated parser extracts text and structure with size and type limits",
            "Structure-aware chunking keeps headings and table context",
            "Embed chunks through the enterprise-embedding alias",
            "Index chunks with tenant, ACL, source, and index-version metadata",
        ],
        chunking_strategy="structure-aware (headings/sections) with token windows",
        chunk_size_tokens=800,
        chunk_overlap_tokens=120,
        embedding_model_alias="enterprise-embedding",
        embedding_dimensions=1536,
        similarity_metric="cosine",
        retrieval_mode="hybrid",
        top_k=8,
        reranking="semantic reranker on the top 30 hybrid candidates",
        grounding_policy="Answer only from retrieved passages, cite sources, and say when the "
        "context is insufficient",
        freshness="Incremental connector sync; deletions propagate within one sync interval",
        acl_enforcement="Security-trimmed filters on tenant and principal groups at query time; "
        "re-check source access before returning citations",
    )
    add_decision(
        design,
        "rag",
        "Hybrid retrieval with security trimming",
        "Combine keyword and vector search with ACL filters evaluated at query time.",
        "Hybrid search improves recall on identifiers and jargon; filters keep tenants isolated.",
        ["Vector-only search", "Post-filtering results in the application"],
        "Embedding dimensions (1536 by default) must be verified against the chosen deployment.",
    )


def _data(design: EnterpriseDesign, req: RequirementsSpec) -> None:
    profile = req.profile
    postgres = _pick(
        profile,
        "Azure Database for PostgreSQL Flexible Server",
        "Amazon RDS for PostgreSQL",
        "managed PostgreSQL",
    )
    stores = [
        DataStore(
            id="store-ledger",
            name="Budget ledger",
            kind=postgres,
            purpose="transactional reservations and settlement",
            region=req.region,
            partition_key="organization_id",
            consistency="serializable transaction",
            retention_days=2555,
            owner_service="svc-admission",
            encryption="encryption at rest with platform keys; TLS 1.2+ in transit",
            backup="point-in-time restore, 35-day retention",
        ),
        DataStore(
            id="store-state",
            name="Conversation and job state" if needs_async_jobs(req) else "Conversation state",
            kind=postgres,
            purpose=_state_purpose(req),
            region=req.region,
            partition_key="tenant_id",
            consistency="read-committed transactions; outbox in the same transaction"
            if needs_queue(req)
            else "read-committed transactions",
            retention_days=365,
            owner_service="svc-app",
            encryption="encryption at rest; row-level security by tenant",
            backup="point-in-time restore, 35-day retention",
        ),
    ]
    if has_rag(req):
        stores.append(
            DataStore(
                id="store-object",
                name="Object storage",
                kind=_pick(profile, "Azure Blob Storage", "Amazon S3", "object storage"),
                purpose="source documents by immutable object reference",
                region=req.region,
                partition_key="tenant_id",
                consistency="read-after-write",
                retention_days=365,
                owner_service="svc-ingestion",
                encryption="encryption at rest; private access only; versioning enabled",
                backup="soft delete and versioning; lifecycle policy",
            )
        )
        stores.append(
            DataStore(
                id="store-vector",
                name="Retrieval index",
                kind=_pick(
                    profile,
                    "Azure AI Search",
                    "Amazon OpenSearch Serverless (vector search)",
                    "managed vector service",
                ),
                purpose="ACL-filtered hybrid retrieval; embedding/index version bound",
                region=req.region,
                partition_key="tenant_id",
                consistency="eventual with versioned index",
                retention_days=365,
                owner_service="svc-ingestion",
                encryption="encryption at rest; private endpoint",
                backup="rebuild from object storage with the recorded index version",
            )
        )
    design.data_stores = stores
    add_decision(
        design,
        "data",
        "PostgreSQL for ledger and state"
        + (", object storage for documents" if has_rag(req) else ""),
        f"Use {postgres} (separate databases) for the budget ledger and application state"
        + (", plus one managed vector index" if has_rag(req) else "")
        + ".",
        "The ledger needs serializable transactions; sharing one server reduces operational "
        "overhead while keeping separate schemas and roles.",
        ["Cosmos DB for state", "Redis as ledger"],
    )


def _infra(design: EnterpriseDesign, req: RequirementsSpec) -> None:
    rag = has_rag(req)
    profiles: dict[str, tuple[str, str, list[CloudResource], list[str]]] = {
        "azure-aca": (
            "azure",
            "Azure Container Apps (workload profiles environment)",
            [
                CloudResource(
                    name="apim", service="API Management", tier="StandardV2", purpose="ingress"
                ),
                CloudResource(
                    name="cae",
                    service="Container Apps environment",
                    tier="Consumption + D4",
                    purpose="application, AI gateway, and workers",
                ),
                CloudResource(
                    name="sb", service="Service Bus", tier="Standard", purpose="job queue + DLQ"
                ),
                CloudResource(
                    name="psql",
                    service="PostgreSQL Flexible Server",
                    tier="General Purpose D2ds_v5",
                    purpose="ledger and state",
                ),
                CloudResource(
                    name="st", service="Storage account", tier="Standard ZRS", purpose="documents"
                ),
                CloudResource(
                    name="kv", service="Key Vault", tier="Standard", purpose="secret references"
                ),
                CloudResource(
                    name="log",
                    service="Log Analytics + Application Insights",
                    tier="PerGB2018",
                    purpose="telemetry",
                ),
            ],
            ["Container Apps environment on a delegated subnet", "Private endpoints for data"],
        ),
        "azure-aks": (
            "azure",
            "Azure Kubernetes Service with KEDA and workload identity",
            [
                CloudResource(
                    name="apim", service="API Management", tier="StandardV2", purpose="ingress"
                ),
                CloudResource(
                    name="aks",
                    service="AKS",
                    tier="Standard tier, 3 zones",
                    purpose="application, AI gateway, and workers",
                ),
                CloudResource(
                    name="sb", service="Service Bus", tier="Standard", purpose="job queue + DLQ"
                ),
                CloudResource(
                    name="psql",
                    service="PostgreSQL Flexible Server",
                    tier="General Purpose D2ds_v5",
                    purpose="ledger and state",
                ),
                CloudResource(
                    name="st", service="Storage account", tier="Standard ZRS", purpose="documents"
                ),
                CloudResource(
                    name="kv", service="Key Vault", tier="Standard", purpose="secret references"
                ),
                CloudResource(
                    name="log",
                    service="Log Analytics + Container Insights",
                    tier="PerGB2018",
                    purpose="telemetry",
                ),
            ],
            ["Azure CNI with network policy", "Private endpoints for data"],
        ),
        "aws-eks": (
            "aws",
            "Amazon EKS with Pod Identity and KEDA",
            [
                CloudResource(
                    name="apigw",
                    service="API Gateway + ALB",
                    tier="regional",
                    purpose="ingress with streaming-capable ALB path",
                ),
                CloudResource(
                    name="eks", service="EKS", tier="managed node group", purpose="workloads"
                ),
                CloudResource(name="sqs", service="SQS", tier="standard", purpose="jobs + DLQ"),
                CloudResource(
                    name="rds",
                    service="RDS for PostgreSQL",
                    tier="db.m7g.large Multi-AZ",
                    purpose="ledger and state",
                ),
                CloudResource(name="s3", service="S3", tier="Standard", purpose="documents"),
                CloudResource(
                    name="secrets",
                    service="Secrets Manager",
                    tier="standard",
                    purpose="managed database credentials",
                ),
                CloudResource(
                    name="cw", service="CloudWatch", tier="standard", purpose="telemetry"
                ),
            ],
            ["Private subnets across three AZs", "VPC endpoints for S3, SQS, and Bedrock"],
        ),
        "agnostic": (
            "agnostic",
            "managed containers",
            [
                CloudResource(
                    name="gateway", service="enterprise gateway", tier="-", purpose="ingress"
                ),
                CloudResource(
                    name="compute", service="managed containers", tier="-", purpose="workloads"
                ),
                CloudResource(name="broker", service="managed broker", tier="-", purpose="jobs"),
                CloudResource(
                    name="db", service="transactional database", tier="-", purpose="ledger"
                ),
                CloudResource(
                    name="objects", service="object storage", tier="-", purpose="documents"
                ),
                CloudResource(
                    name="secrets", service="secret manager", tier="-", purpose="secrets"
                ),
                CloudResource(name="telemetry", service="telemetry", tier="-", purpose="ops"),
            ],
            ["Private networking between workloads and data services"],
        ),
    }
    cloud, compute, resources, networking = profiles[req.profile]
    if not needs_queue(req):
        resources = [item for item in resources if item.name not in {"sb", "sqs", "broker"}]
    if not rag:
        resources = [item for item in resources if item.name not in {"st", "s3", "objects"}]
    if rag and cloud == "azure":
        resources.append(
            CloudResource(
                name="srch", service="Azure AI Search", tier="Standard S1", purpose="retrieval"
            )
        )
    if rag and cloud == "aws":
        resources.append(
            CloudResource(
                name="aoss",
                service="OpenSearch Serverless",
                tier="vector collection",
                purpose="retrieval",
            )
        )
    networking = [
        *networking,
        "Only the enterprise gateway is internet-facing; TLS 1.2+ everywhere",
        "Egress to managed AI endpoints through an allowlisted path",
    ]
    design.deployment = DeploymentProfile(
        name=req.profile,
        hosting_cloud=cloud,
        region=req.region,
        resources=[item.service for item in resources],
        compute=compute,
        environments=["dev", "test", "prod"],
        networking=networking,
        resource_details=resources,
        iac_notes=[
            "Separate Terraform state per environment and cloud",
            "Application images are user-supplied immutable references",
            "Review and plan in a pipeline; ArchAI never applies infrastructure",
        ],
    )
    add_decision(
        design,
        "infra",
        f"Deployment profile {req.profile}",
        f"Host workloads on {compute} in {req.region}.",
        "Matches the selected profile; managed services minimize operational load.",
        [name for name in ("azure-aca", "azure-aks", "aws-eks") if name != req.profile],
    )


def _resilience(design: EnterpriseDesign, req: RequirementsSpec) -> None:
    broker = _pick(req.profile, "Azure Service Bus", "AWS SQS", "validated managed broker")
    kinds = {service.kind for service in design.services}
    if needs_queue(req):
        design.queue_policy = QueuePolicy(
            broker=broker, max_attempts=5, max_age_seconds=3600, dlq_owner="operations"
        )
    else:
        design.queue_policy = None
    dr = {
        "single-cloud": "Zone-redundant services in one region; restore from backups to a "
        "secondary region by runbook",
        "provider-failover": "Model-provider failover only; the application remains in its "
        "hosting region. This is not application disaster recovery",
        "application-dr": "Warm standby environment in a recovery region with separate IaC "
        "roots, data replication, budget authority, and traffic switching",
    }[req.topology]
    timeouts = [
        "Gateway → application: 120 s (streaming)",
        "Application → model admission: 5 s",
        "AI gateway → provider: 60 s first token, 120 s total",
    ]
    if "worker" in kinds:
        timeouts.append("Worker job: 15 min with lock renewal")
    elif "ingestion" in kinds:
        timeouts.append("Ingestion job: 15 min with lock renewal")
    scaling = ["Application: scale on concurrent HTTP requests"]
    if design.queue_policy:
        worker_label = "Workers" if "worker" in kinds else "Ingestion"
        scaling.append(f"{worker_label}: scale on {broker} queue length, capped by provider quota")
    scaling.append("Liveness never depends on provider health; readiness reports degraded state")
    degraded = [
        "Primary provider unavailable → approved fallback route if eligible",
        "Budget authority unavailable → reject new chargeable work (hard budget)",
    ]
    if has_rag(req):
        degraded.append(
            "Retrieval unavailable → answer that sources are unavailable, no ungrounded answer"
        )
    design.resilience = ResiliencePlan(
        retry_policy="AI gateway: one retry on timeout/429/5xx with jittered backoff, honouring "
        "Retry-After and the request deadline",
        retry_owner="ai-gateway",
        circuit_breaker="Per-endpoint closed/open/half-open; open after 5 failures in 30 s; "
        "half-open probe budget of 2 requests",
        timeouts=timeouts,
        scaling_rules=scaling,
        degraded_modes=degraded,
        dr_strategy=dr,
        rto_minutes=req.rto_minutes,
        rpo_minutes=req.rpo_minutes,
    )
    if design.queue_policy:
        add_decision(
            design,
            "resilience",
            f"{broker} with at-least-once delivery",
            f"Use {broker} with DLQ, idempotent handlers, and outbox publishing.",
            "Managed broker with dead-lettering matches the hosting profile.",
            ["Celery with Redis", "In-process background tasks"],
            "Handlers must be idempotent; exactly-once external side effects are not claimed.",
        )
    else:
        add_decision(
            design,
            "resilience",
            "Synchronous request path with provider retry only",
            "Keep retries on the AI gateway; do not introduce a job queue on this revision.",
            "No long-running jobs or ingestion workers are in scope.",
            ["Managed broker with DLQ"],
        )


def _auth(design: EnterpriseDesign, req: RequirementsSpec) -> None:
    idp = req.identity_provider or "Entra ID"
    audience = f"api://{design.project}"
    flows = [
        OAuthFlow(
            name="User sign-in",
            grant_type="authorization_code_pkce",
            client=", ".join(req.client_channels) or "web client",
            audience=audience,
            scopes=["openid", "profile", "offline_access", f"{audience}/chat.invoke"],
            pkce=True,
            token_lifetime_minutes=60,
            notes="Public clients use PKCE; refresh tokens are rotated and bound to the client.",
        ),
        OAuthFlow(
            name="Service-to-service",
            grant_type="client_credentials",
            client="internal services via workload/managed identity",
            audience=f"{audience}/internal",
            scopes=[f"{audience}/internal/.default"],
            token_lifetime_minutes=60,
            notes="No client secrets: federated workload identity issues short-lived tokens.",
        ),
    ]
    if uses_tools(req) and req.integrations:
        flows.append(
            OAuthFlow(
                name="Delegated tool access",
                grant_type="on_behalf_of",
                client="svc-tools",
                audience="downstream business APIs",
                scopes=["least-privilege delegated scopes per integration"],
                token_lifetime_minutes=15,
                notes="Tools act with the user's delegated permissions, never broader app rights.",
            )
        )
    role_names = req.user_roles or ["user", "admin"]
    roles: list[RoleDefinition] = []
    for name in role_names:
        lowered = name.lower()
        if "admin" in lowered:
            permissions = [
                "chat.invoke",
                "chat.read",
                "budgets.manage",
                "audit.read",
                "config.manage",
            ]
        elif "approv" in lowered or "finance" in lowered:
            permissions = ["chat.invoke", "chat.read", "approvals.decide"]
        elif any(word in lowered for word in ("author", "editor", "curator", "content")):
            permissions = ["chat.invoke", "chat.read", "documents.write"]
        else:
            permissions = ["chat.invoke", "chat.read", "feedback.write"]
            if needs_async_jobs(req):
                permissions[2:2] = ["jobs.submit", "jobs.read"]
        roles.append(
            RoleDefinition(
                name=name, description=f"Application role for {name}", permissions=permissions
            )
        )
    identity_type = _pick(
        req.profile,
        "user-assigned managed identity",
        "EKS Pod Identity IAM role",
        "workload identity",
    )
    identities = [
        ServiceIdentity(
            service_id=service.id,
            identity_type=identity_type,
            grants=_grants_for(service.kind, req.profile),
        )
        for service in design.services
        if service.kind not in {"gateway", "operations"}
    ]
    design.identity_policy = IdentityPolicy(
        idp=idp,
        tenant_mode=req.tenant_isolation,
        required_claims=list(REQUIRED_CLAIMS),
        object_level_authorization=True,
        tenant_mapping="Tenant from the validated tid claim, department from directory groups; "
        "caller-supplied tenant or department headers are ignored",
        oauth_flows=flows,
        roles=roles,
        service_identities=identities,
        session_management="Short-lived access tokens (≤60 min), rotating refresh tokens, "
        "server-side session revocation on sign-out",
    )
    add_decision(
        design,
        "auth",
        f"{idp} OIDC with workload identity",
        "Users authenticate with authorization code + PKCE; services use federated workload "
        "identity and client-credentials tokens without stored secrets.",
        "Removes long-lived secrets and gives every call a verifiable principal for budgets "
        "and ACLs.",
        ["API keys per client", "Shared service accounts"],
    )


def _grants_for(kind: str, profile: str) -> list[str]:
    cloud = cloud_of(profile)
    queue = {"azure": "Service Bus Data Sender/Receiver", "aws": "sqs:SendMessage/ReceiveMessage"}
    blob = {"azure": "Storage Blob Data Contributor", "aws": "s3:GetObject/PutObject"}
    search = {"azure": "Search Index Data Reader", "aws": "aoss:APIAccessAll (collection)"}
    secret = {"azure": "Key Vault Secrets User", "aws": "secretsmanager:GetSecretValue"}
    grants = {
        "application": [queue.get(cloud, "broker send"), "database: app_state read/write"],
        "policy": ["database: budget_ledger read/write"],
        "ai-gateway": [
            secret.get(cloud, "secret read"),
            "managed model invoke (Cognitive Services OpenAI User / bedrock:InvokeModel)",
        ],
        "retrieval": [search.get(cloud, "index read")],
        "ingestion": [
            queue.get(cloud, "broker receive"),
            blob.get(cloud, "object read"),
            "index write",
        ],
        "worker": [queue.get(cloud, "broker receive"), "database: app_state read/write"],
        "tool-executor": [secret.get(cloud, "secret read"), "delegated tool scopes"],
    }
    return grants.get(kind, ["least privilege per dependency"])


def _guard(design: EnterpriseDesign, req: RequirementsSpec) -> None:
    controls = [
        GuardrailControl(
            id="guard-input",
            stage="input",
            control="size, content, and task authorization",
            owner="application",
            enforcement="custom-runtime-required",
        )
    ]
    if has_rag(req):
        controls.append(
            GuardrailControl(
                id="guard-retrieval",
                stage="retrieval",
                control="tenant and object ACL filter",
                owner="application",
                enforcement="custom-runtime-required",
            )
        )
    if uses_tools(req):
        controls.append(
            GuardrailControl(
                id="guard-tools",
                stage="tool",
                control="schema, authorization, and exact-argument approval",
                owner="workflow",
                enforcement="custom-runtime-required",
            )
        )
        if req.tool_side_effects == "forbidden":
            controls.append(
                GuardrailControl(
                    id="guard-no-side-effects",
                    stage="execution",
                    control="read-only tool credentials; state-changing tools are not registered",
                    owner="platform",
                    enforcement="custom-runtime-required",
                )
            )
    controls.append(
        GuardrailControl(
            id="guard-output",
            stage="output",
            control="schema and sensitive-data release validation",
            owner="application",
            enforcement="custom-runtime-required",
        )
    )
    controls.append(
        GuardrailControl(
            id="guard-audit",
            stage="audit",
            control="immutable audit of prompts metadata, tool calls, and approvals (redacted)",
            owner="security",
            enforcement="custom-runtime-required",
        )
    )
    design.guardrails = controls


def _security(design: EnterpriseDesign, req: RequirementsSpec) -> None:
    design.risks = [
        Risk(
            id="risk-injection",
            title="Untrusted content influences model or tool behavior",
            severity="high",
            mitigation="Treat content as data; enforce authorization outside prompts and "
            "validate tool arguments",
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
    threats = [
        Threat(
            id="threat-prompt-injection",
            title="Prompt injection through user input or retrieved content",
            stride="tampering",
            owasp_ref="LLM01:2025",
            severity="high",
            affected=["svc-app", "svc-retrieval", "svc-tools"],
            mitigation="Content is data; authorization and tool permissions are enforced in "
            "code; injection screening is one defensive layer",
            owner="security",
            residual_risk="medium",
        ),
        Threat(
            id="threat-cross-tenant-disclosure",
            title="Sensitive information disclosed across tenants or permissions",
            stride="information-disclosure",
            owasp_ref="LLM02:2025",
            severity="critical" if req.tenant_isolation == "multi" else "high",
            affected=["svc-retrieval", "store-vector", "svc-app"],
            mitigation="Tenant and ACL filters at retrieval, cache, job status, and audit views",
            owner="security",
            residual_risk="low",
        ),
        Threat(
            id="threat-unbounded-consumption",
            title="Unbounded consumption drives cost or denial of service",
            stride="denial-of-service",
            owasp_ref="LLM10:2025",
            severity="high",
            affected=["svc-admission", "svc-ai-gateway"],
            mitigation="Rate limits, token ceilings, hard budget reservations, and bounded retries",
            owner="finops",
            residual_risk="low",
        ),
        Threat(
            id="threat-output-handling",
            title="Model output used unsafely by downstream systems",
            stride="tampering",
            owasp_ref="LLM05:2025",
            severity="medium",
            affected=["svc-app"],
            mitigation="Schema-validate outputs, encode before rendering, never execute output",
            owner="application",
            residual_risk="low",
        ),
        Threat(
            id="threat-prompt-leakage",
            title="System prompt or configuration leakage",
            stride="information-disclosure",
            owasp_ref="LLM07:2025",
            severity="medium",
            affected=["svc-app"],
            mitigation="No secrets in prompts; secrets stay in the vault and code paths",
            owner="application",
            residual_risk="low",
        ),
        Threat(
            id="threat-token-spoofing",
            title="Forged or replayed access tokens",
            stride="spoofing",
            severity="high",
            affected=["svc-ingress"],
            mitigation="Validate issuer, audience, signature, expiry, and tenant at the gateway; "
            "short token lifetimes",
            owner="platform",
            residual_risk="low",
        ),
        Threat(
            id="threat-supply-chain",
            title="Compromised dependency, image, or model deployment",
            stride="tampering",
            owasp_ref="LLM03:2025",
            severity="medium",
            affected=["all services"],
            mitigation="Pinned dependencies, signed images, SBOM, approved model catalog",
            owner="platform",
            residual_risk="medium",
        ),
        Threat(
            id="threat-misinformation",
            title="Ungrounded or incorrect answers presented as fact",
            stride="tampering",
            owasp_ref="LLM09:2025",
            severity="medium",
            affected=["svc-app"],
            mitigation="Grounding policy with citations, evaluation gates, and user feedback",
            owner="ai-quality",
            residual_risk="medium",
        ),
    ]
    if uses_tools(req):
        threats.append(
            Threat(
                id="threat-excessive-agency",
                title="Agent performs unauthorized or unintended actions",
                stride="elevation-of-privilege",
                owasp_ref="LLM06:2025",
                severity="critical" if req.tool_side_effects == "allowed" else "high",
                affected=["svc-tools"],
                mitigation="Least-privilege tools, exact-argument approval, idempotency keys, "
                "and no automatic replay of uncertain actions",
                owner="security",
                residual_risk="medium",
            )
        )
        threats.append(
            Threat(
                id="threat-approval-repudiation",
                title="Approver denies having approved an action",
                stride="repudiation",
                severity="medium",
                affected=["svc-tools", "store-state"],
                mitigation="Signed, immutable approval records bound to argument hashes",
                owner="security",
                residual_risk="low",
            )
        )
    if has_rag(req):
        threats.append(
            Threat(
                id="threat-vector-weakness",
                title="Embedding/index weaknesses bypass ACLs or poison retrieval",
                stride="information-disclosure",
                owasp_ref="LLM08:2025",
                severity="high",
                affected=["store-vector", "svc-ingestion"],
                mitigation="ACL metadata on every chunk, source trust checks, index versioning",
                owner="data-platform",
                residual_risk="medium",
            )
        )
    known = {service.id for service in design.services} | {store.id for store in design.data_stores}
    known.add("all services")
    for threat in threats:
        threat.affected = [item for item in threat.affected if item in known]
    design.threats = threats


def _observe(design: EnterpriseDesign, req: RequirementsSpec) -> None:
    latency = req.latency_p95_ms or 8000
    design.observability = ObservabilityPlan(
        tracing="OpenTelemetry",
        model_analytics="Langfuse",
        correlation_ids=list(REQUIRED_CORRELATION_IDS),
        redaction_required=True,
        metrics=[
            MetricSpec(
                name="time_to_first_token_ms",
                description="Latency until the first streamed token",
                slo="p95 < 1500 ms",
                alert="p95 > 2500 ms for 10 min",
            ),
            MetricSpec(
                name="completion_latency_ms",
                description="End-to-end request latency",
                slo=f"p95 < {latency} ms",
                alert=f"p95 > {int(latency * 1.5)} ms for 10 min",
            ),
            MetricSpec(
                name="provider_error_rate",
                description="Errors by class (timeout, 429, 5xx, refusal) per endpoint",
                slo="< 1% excluding refusals",
                alert="> 5% for 5 min or circuit opened",
            ),
            MetricSpec(
                name="retry_amplification",
                description="Attempts per logical request",
                slo="< 1.2",
                alert="> 1.5 for 15 min",
            ),
            MetricSpec(
                name="budget_unresolved_spend",
                description="Dispatched reservations awaiting reconciliation",
                slo="< 1% of monthly budget",
                alert="> 2% of monthly budget",
            ),
            MetricSpec(
                name="quota_headroom",
                description="Remaining TPM/RPM per endpoint",
                slo="> 20% at peak",
                alert="< 10% for 5 min",
            ),
            MetricSpec(
                name="queue_oldest_message_age_s",
                description="Age of the oldest queued job; DLQ depth",
                slo="< 300 s",
                alert="> 900 s or DLQ > 0",
            ),
            MetricSpec(
                name="policy_violations",
                description="Guardrail blocks and authorization denials",
                slo="tracked",
                alert="spike > 3× baseline",
            ),
        ],
        dashboards=[
            "Service health and SLOs",
            "Model routes, errors, and fallback",
            "Budget, reservations, and spend by department",
            "Queue and worker health",
        ],
        log_retention_days=90,
        sampling="100% of errors and policy events; 10–20% of successful traces",
        redaction="Strip prompts/responses of personal data before export; store hashes and "
        "decision summaries, never hidden reasoning",
    )


def _eval(design: EnterpriseDesign, req: RequirementsSpec) -> None:
    metrics = [
        EvalMetric(
            name="task success",
            target="≥ 85% on golden set",
            method="LLM-as-judge + human spot checks",
        ),
        EvalMetric(name="safety policy violations", target="0 critical", method="red-team suite"),
        EvalMetric(
            name="p95 latency", target=f"≤ {req.latency_p95_ms or 8000} ms", method="load test"
        ),
        EvalMetric(name="cost per request", target="within budget envelope", method="usage replay"),
    ]
    if has_rag(req):
        metrics.insert(
            0,
            EvalMetric(
                name="groundedness / citation accuracy",
                target="≥ 90%",
                method="reference-answer comparison",
            ),
        )
        metrics.insert(
            1, EvalMetric(name="retrieval recall@k", target="≥ 0.8", method="labelled queries")
        )
    design.eval_plan = EvalPlan(
        datasets=[
            "Golden question set curated by business owners",
            "Adversarial prompt-injection and data-exfiltration set",
            "Production feedback samples (redacted)",
        ],
        metrics=metrics,
        cadence="On every prompt/model/index change and nightly regression",
        release_gates=[
            "No regression > 2 points on task success",
            "Zero critical safety failures",
            "Every fallback route evaluated before it is eligible",
        ],
    )


def _cost(design: EnterpriseDesign, req: RequirementsSpec) -> None:
    design.capacity = estimate_capacity(req)
    chat = chat_endpoints(design)
    if chat:
        design.costs = [
            estimate_cost(req, chat[0]),
            estimate_cost(req, chat[0], scenario="peak", rps=req.peak_rps),
        ]
        if len(chat) > 1:
            design.costs.append(
                estimate_cost(
                    req, chat[1], scenario="failover", rps=req.peak_rps, attempts=Decimal("1.5")
                )
            )
    else:
        design.costs = []


def _noop(design: EnterpriseDesign, req: RequirementsSpec) -> None:
    del design, req


_BUILDERS = {
    "requirements": _noop,
    "system": _system,
    "api": _api,
    "routing": _routing,
    "budget": _budget,
    "cache": _cache,
    "workflow": _workflow,
    "rag": _rag,
    "data": _data,
    "infra": _infra,
    "resilience": _resilience,
    "auth": _auth,
    "guard": _guard,
    "security": _security,
    "observe": _observe,
    "eval": _eval,
    "cost": _cost,
    "diagram": _noop,
    "doc": _noop,
}


# ---------------------------------------------------------------- graph


def lane_for(kind: str) -> str:
    return {
        "client": LANES[0],
        "identity": LANES[0],
        "frontend": LANES[1],
        "gateway": LANES[1],
        "application": LANES[2],
        "orchestration": LANES[2],
        "policy": LANES[2],
        "retrieval": LANES[2],
        "tool-executor": LANES[2],
        "integration": LANES[2],
        "ai-gateway": LANES[4],
        "managed-model": LANES[4],
        "ingestion": LANES[3],
        "worker": LANES[3],
        "data": LANES[3],
        "queue": LANES[3],
        "operations": LANES[5],
    }.get(kind, LANES[2])


def build_graph(design: EnterpriseDesign) -> ArchitectureGraph:
    nodes = [
        Node(id="client", label="Enterprise clients", kind="client", lane=LANES[0]),
    ]
    if design.identity_policy:
        nodes.append(
            Node(
                id="identity",
                label=design.identity_policy.idp,
                kind="identity",
                lane=LANES[0],
            )
        )
    nodes.extend(
        Node(id=service.id, label=service.name, kind=service.kind, lane=lane_for(service.kind))
        for service in design.services
    )
    if design.queue_policy:
        nodes.append(
            Node(
                id="queue",
                label=f"{design.queue_policy.broker} + DLQ",
                kind="queue",
                lane=LANES[3],
            )
        )
    nodes.extend(
        Node(id=store.id, label=store.name, kind="data", lane=LANES[3])
        for store in design.data_stores
    )
    nodes.extend(
        Node(
            id=endpoint.id,
            label=f"{endpoint.provider}"
            + (" embeddings" if "embeddings" in endpoint.modalities else " model endpoint"),
            kind="managed-model",
            lane=LANES[4],
        )
        for endpoint in design.endpoints
    )
    node_ids = {node.id for node in nodes}
    edges: list[Edge] = []
    seen: set[tuple[str, str]] = set()

    def add(source: str, target: str, label: str, kind: str = "data") -> None:
        if source in node_ids and target in node_ids and (source, target) not in seen:
            seen.add((source, target))
            edges.append(
                Edge(
                    id=f"edge-{len(edges) + 1:02d}-{source}-{target}"[:80],
                    source=source,
                    target=target,
                    label=label,
                    kind=kind,
                )
            )

    gateways = [service.id for service in design.services if service.kind == "gateway"]
    if design.identity_policy:
        add("client", "identity", "sign in (OIDC + PKCE)", "identity")
    for gateway in gateways or ["svc-app"]:
        add("client", gateway, "HTTPS + bearer token")
        if design.identity_policy:
            add("identity", gateway, "token signing keys", "identity")
    store_ids = {store.id for store in design.data_stores}
    for service in design.services:
        for dependency in service.depends_on:
            label = "reads/writes" if dependency in store_ids else "calls"
            add(service.id, dependency, label)
    ai_gateways = [service.id for service in design.services if service.kind == "ai-gateway"]
    fallback_ids = {item for alias in design.model_aliases for item in alias.fallback_endpoint_ids}
    for gateway in ai_gateways:
        for endpoint in design.endpoints:
            if endpoint.id in fallback_ids:
                add(gateway, endpoint.id, "approved fallback", "fallback")
            else:
                add(gateway, endpoint.id, "managed API call")
    if design.queue_policy:
        producers = [
            service.id
            for service in design.services
            if service.kind in {"application", "orchestration"}
        ]
        for producer in producers[:1]:
            add(producer, "queue", "outbox → job message")
        for service in design.services:
            if service.kind in {"worker", "ingestion"}:
                add("queue", service.id, "deliver (at-least-once)")
    observers = [service.id for service in design.services if service.kind == "operations"]
    for observer in observers[:1]:
        for service in design.services:
            if service.kind in {
                "application",
                "orchestration",
                "ai-gateway",
                "worker",
                "ingestion",
            }:
                add(service.id, observer, "telemetry", "telemetry")
    return ArchitectureGraph(nodes=nodes, edges=edges)
