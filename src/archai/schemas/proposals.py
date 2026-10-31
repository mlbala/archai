"""Architect-model proposal schemas.

These models are deliberately simple so that both OpenAI strict structured outputs and Gemini JSON
schema mode accept them: every field is required, there are no defaults, and only strings, numbers,
booleans, enums, lists, and nested objects are used. Proposals are untrusted until the deterministic
merge step validates and normalizes them into canonical state.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, create_model


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- role 1: requirements


class FieldSuggestion(Proposal):
    field: str
    value: str
    rationale: str
    source_quote: str


class RequirementsAnalysis(Proposal):
    summary: str
    suggestions: list[FieldSuggestion]
    clarifying_questions: list[str]
    detected_risks: list[str]


class PersonaProposal(Proposal):
    name: str
    needs: str


class JourneyProposal(Proposal):
    name: str
    steps: list[str]


class RequirementProposal(Proposal):
    id: str
    statement: str
    priority: Literal["must", "should", "could"]


class NFRProposal(Proposal):
    id: str
    category: str
    statement: str
    target: str


class PRDProposal(Proposal):
    summary: str
    problem_statement: str
    goals: list[str]
    non_goals: list[str]
    personas: list[PersonaProposal]
    journeys: list[JourneyProposal]
    functional_requirements: list[RequirementProposal]
    non_functional_requirements: list[NFRProposal]
    acceptance_metrics: list[str]
    open_questions: list[str]


class DecisionProposal(Proposal):
    component: str
    title: str
    decision: str
    rationale: str
    alternatives: list[str]
    consequences: str


# ---------------------------------------------------------------- role 3: cloud, data, resilience

ServiceKind = Literal[
    "frontend",
    "gateway",
    "application",
    "orchestration",
    "policy",
    "ai-gateway",
    "retrieval",
    "ingestion",
    "worker",
    "tool-executor",
    "integration",
    "operations",
]


class ServiceProposal(Proposal):
    id: str
    name: str
    kind: ServiceKind
    responsibilities: list[str]
    technology: str
    scaling: str
    exposes: list[str]
    depends_on: list[str]
    data_owned: list[str]


class DataStoreProposal(Proposal):
    id: str
    name: str
    kind: str
    purpose: str
    owner_service: str
    partition_key: str
    consistency: str
    retention_days: int
    encryption: str
    backup: str


class WorkflowProposal(Proposal):
    id: str
    name: str
    trigger: str
    description: str
    steps: list[str]
    hitl_required: bool


class RAGProposal(Proposal):
    applicable: bool
    ingestion_steps: list[str]
    chunking_strategy: str
    chunk_size_tokens: int
    chunk_overlap_tokens: int
    embedding_model_alias: str
    embedding_dimensions: int
    similarity_metric: str
    retrieval_mode: Literal["vector", "keyword", "hybrid"]
    top_k: int
    reranking: str
    grounding_policy: str
    freshness: str
    acl_enforcement: str


class CloudResourceProposal(Proposal):
    name: str
    service: str
    tier: str
    purpose: str


class InfraProposal(Proposal):
    compute: str
    environments: list[str]
    networking: list[str]
    resources: list[CloudResourceProposal]
    iac_notes: list[str]


class ResilienceProposal(Proposal):
    max_attempts: int
    max_age_seconds: int
    dlq_owner: str
    retry_policy: str
    retry_owner: str
    circuit_breaker: str
    timeouts: list[str]
    scaling_rules: list[str]
    degraded_modes: list[str]
    dr_strategy: str


# ---------------------------------------------------------------- role 2: API, routing, budgets

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]


class APIContractProposal(Proposal):
    id: str
    method: HttpMethod
    path: str
    summary: str
    service_id: str
    # How a caller authenticates this operation; "" means the user's OIDC bearer token.
    auth: str
    scopes: list[str]
    streaming: bool
    rate_limit_rpm: int
    request_fields: list[str]
    response_fields: list[str]


class ModelAliasProposal(Proposal):
    id: str
    task: str
    required_capabilities: list[str]
    max_output_tokens: int
    primary_provider: str
    fallback_providers: list[str]
    quality_gate: str


class EndpointProposal(Proposal):
    provider: str
    region: str
    purpose: Literal["chat", "embedding"]
    deployment_role: Literal["primary", "recovery"]
    reason: str


class RoutingPolicyProposal(Proposal):
    eligibility_rules: list[str]
    ranking: str
    retry_owner: str
    max_attempts: int
    circuit_breaker: str
    stream_policy: str


class BudgetAllocationProposal(Proposal):
    scope: str
    share_percent: float


class BudgetProposal(Proposal):
    allocations: list[BudgetAllocationProposal]
    soft_limit_percent: int
    per_request_token_ceiling: int
    per_workflow_step_ceiling: int
    rationale: str


class CacheProposal(Proposal):
    exact_enabled: bool
    semantic_enabled: bool
    ttl_seconds: int
    semantic_similarity_threshold: float
    provider_prompt_caching: bool
    retrieval_cache_ttl_seconds: int
    bypass_conditions: list[str]
    invalidation_events: list[str]
    rationale: str


# ---------------------------------------------------------------- role 4: identity and security

GrantType = Literal[
    "authorization_code_pkce",
    "client_credentials",
    "on_behalf_of",
    "device_code",
    "refresh_token",
    "token_exchange",
]


class OAuthFlowProposal(Proposal):
    name: str
    grant_type: GrantType
    client: str
    audience: str
    scopes: list[str]
    token_lifetime_minutes: int
    notes: str


class RoleProposal(Proposal):
    name: str
    description: str
    permissions: list[str]


class ServiceIdentityProposal(Proposal):
    service_id: str
    identity_type: str
    grants: list[str]


class IdentityProposal(Proposal):
    idp: str
    tenant_mapping: str
    oauth_flows: list[OAuthFlowProposal]
    roles: list[RoleProposal]
    service_identities: list[ServiceIdentityProposal]
    extra_required_claims: list[str]
    session_management: str


GuardStage = Literal["input", "retrieval", "tool", "execution", "output", "audit"]


class GuardrailProposal(Proposal):
    id: str
    stage: GuardStage
    control: str
    owner: str
    enforcement: Literal["native", "custom-runtime-required", "design-only"]


Stride = Literal[
    "spoofing",
    "tampering",
    "repudiation",
    "information-disclosure",
    "denial-of-service",
    "elevation-of-privilege",
]
Severity = Literal["low", "medium", "high", "critical"]


class ThreatProposal(Proposal):
    id: str
    title: str
    stride: Stride
    owasp_ref: str
    severity: Severity
    affected: list[str]
    mitigation: str
    owner: str
    residual_risk: Literal["low", "medium", "high"]


class MetricProposal(Proposal):
    name: str
    description: str
    slo: str
    alert: str


class ObservabilityProposal(Proposal):
    tracing: str
    model_analytics: str
    extra_correlation_ids: list[str]
    metrics: list[MetricProposal]
    dashboards: list[str]
    log_retention_days: int
    sampling: str
    redaction: str


class EvalMetricProposal(Proposal):
    name: str
    target: str
    method: str


class EvalProposal(Proposal):
    datasets: list[str]
    metrics: list[EvalMetricProposal]
    cadence: str
    release_gates: list[str]
    routes_covered: str


# ---------------------------------------------------------------- chief architect (planner)


class PlannedServiceProposal(Proposal):
    id: str
    name: str
    kind: ServiceKind
    purpose: str
    depends_on: list[str]


class PlannedInterfaceProposal(Proposal):
    source: str
    target: str
    style: Literal["sync-http", "streaming", "async-queue", "event", "batch", "tool-call"]
    purpose: str


class PlannedChoiceProposal(Proposal):
    component: str
    choice: str
    reason: str


class ArchitecturePlanProposal(Proposal):
    style: str
    summary: str
    services: list[PlannedServiceProposal]
    interfaces: list[PlannedInterfaceProposal]
    key_choices: list[PlannedChoiceProposal]
    default_changes: list[PlannedChoiceProposal]
    risks: list[str]


# ---------------------------------------------------------------- role 5: verifier


class FindingProposal(Proposal):
    severity: Literal["blocking", "warning", "info"]
    component: str
    # Design fields the fix must change, e.g. "services.svc-retrieval.depends_on".
    fields: list[str]
    # Id of the earlier finding this one repeats, or "" when it is new.
    same_as: str
    issue: str
    recommendation: str


class CriterionResultProposal(Proposal):
    id: str
    status: Literal["pass", "fail"]
    # The ids that show the criterion is met, or what is missing when it is not.
    evidence: str
    fields: list[str]
    recommendation: str


class DecisionNeededProposal(Proposal):
    question: str
    why: str
    options: list[str]
    components: list[str]


class VerificationReport(Proposal):
    summary: str
    criteria: list[CriterionResultProposal]
    findings: list[FindingProposal]
    decisions_needed: list[DecisionNeededProposal]


# ---------------------------------------------------------------- per-component proposal fields

COMPONENT_FIELDS: dict[str, tuple[str, Any]] = {
    "system": ("services", list[ServiceProposal]),
    "workflow": ("workflows", list[WorkflowProposal]),
    "rag": ("rag", RAGProposal),
    "data": ("data_stores", list[DataStoreProposal]),
    "infra": ("infra", InfraProposal),
    "resilience": ("resilience", ResilienceProposal),
    "api": ("api_contracts", list[APIContractProposal]),
    "routing": ("routing", RoutingPolicyProposal),
    "budget": ("budget", BudgetProposal),
    "cache": ("cache", CacheProposal),
    "auth": ("identity", IdentityProposal),
    "guard": ("guardrails", list[GuardrailProposal]),
    "security": ("threats", list[ThreatProposal]),
    "observe": ("observability", ObservabilityProposal),
    "eval": ("evaluation", EvalProposal),
}
EXTRA_FIELDS: dict[str, list[tuple[str, Any]]] = {
    "routing": [
        ("model_aliases", list[ModelAliasProposal]),
        # Deployments to add beyond existing_design.endpoints; empty when none are needed.
        ("endpoints", list[EndpointProposal]),
    ],
}


def scoped_proposal_model(role: str, components: list[str], patch: bool = False) -> type[Proposal]:
    """Build a proposal schema containing only the selected components' fields.

    ``patch`` adds ``remove_ids`` for repairs, which return only the items they change.
    """
    fields: dict[str, Any] = {}
    for component in components:
        if component not in COMPONENT_FIELDS:
            continue
        name, annotation = COMPONENT_FIELDS[component]
        fields[name] = (annotation, ...)
        for extra_name, extra_annotation in EXTRA_FIELDS.get(component, []):
            fields[extra_name] = (extra_annotation, ...)
    fields["decisions"] = (list[DecisionProposal], ...)
    if patch:
        fields["remove_ids"] = (list[str], ...)
    model_name = "".join(part.title() for part in [role, *components]) + "Proposal"
    model: type[Proposal] = create_model(model_name, __base__=Proposal, **fields)
    return model
