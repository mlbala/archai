from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Provenance(StrEnum):
    provided = "provided"
    inferred = "inferred"
    assumed = "assumed"
    missing = "missing"
    conflicting = "conflicting"
    not_applicable = "not_applicable"
    user_set = "user_set"


class ComponentStatus(StrEnum):
    missing = "missing"
    draft = "draft"
    valid = "valid"
    stale = "stale"
    blocked = "blocked"
    not_applicable = "not_applicable"


class EvidenceRef(StrictModel):
    source_id: str
    location: str | None = None
    value: Any = None
    unit: str | None = None
    provenance: Provenance = Provenance.provided
    rationale: str | None = None


class SourceDocument(StrictModel):
    id: str
    name: str
    sha256: str
    media_type: str
    stored_path: str


class Assumption(StrictModel):
    id: str
    statement: str
    rationale: str
    critical: bool = False


class Conflict(StrictModel):
    id: str
    field: str
    values: list[Any]
    message: str
    blocking: bool = True


class Clarification(StrictModel):
    question: str
    answer: str


class Decision(StrictModel):
    id: str
    field: str
    value: Any
    rationale: str
    provenance: Provenance


class Risk(StrictModel):
    id: str
    title: str
    severity: Literal["low", "medium", "high", "critical"]
    mitigation: str
    owner: str


DataClassification = Literal["public", "internal", "confidential", "restricted"]


class RequirementsSpec(StrictModel):
    idea: str
    business_outcome: str
    users: list[str]
    archetypes: list[str]
    region: str
    data_residency: list[str]
    tenant_isolation: Literal["single", "multi"]
    allowed_target_providers: list[str]
    tool_side_effects: Literal["forbidden", "approval", "allowed"]
    avg_rps: Decimal = Field(gt=0)
    peak_rps: Decimal = Field(gt=0)
    input_tokens: int = Field(gt=0)
    output_tokens: int = Field(gt=0)
    model_calls_per_request: Decimal = Field(gt=0)
    monthly_budget: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    availability_target: Decimal = Field(gt=0, le=Decimal("100"))
    profile: Literal["azure-aca", "azure-aks", "aws-eks", "agnostic"]
    topology: Literal["single-cloud", "provider-failover", "application-dr"]
    # Optional enrichment collected by the interview; absent values are never invented.
    identity_provider: str | None = None
    user_roles: list[str] = Field(default_factory=list)
    client_channels: list[str] = Field(default_factory=list)
    integrations: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    data_classification: DataClassification | None = None
    compliance: list[str] = Field(default_factory=list)
    latency_p95_ms: int | None = Field(default=None, gt=0)
    rto_minutes: int | None = Field(default=None, gt=0)
    rpo_minutes: int | None = Field(default=None, ge=0)
    documents_per_day: int | None = Field(default=None, ge=0)
    existing_services: list[str] = Field(default_factory=list)
    notes: str | None = None
    clarifications: list[Clarification] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_peak(self) -> RequirementsSpec:
        if self.peak_rps < self.avg_rps:
            raise ValueError("peak_rps must be greater than or equal to avg_rps")
        return self


class Persona(StrictModel):
    name: str
    needs: str


class Journey(StrictModel):
    name: str
    steps: list[str]


class RequirementItem(StrictModel):
    id: str
    statement: str
    priority: Literal["must", "should", "could"] = "must"


class NFRItem(StrictModel):
    id: str
    category: str
    statement: str
    target: str


class PRD(StrictModel):
    summary: str = ""
    problem_statement: str
    goals: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    personas: list[Persona] = Field(default_factory=list)
    journeys: list[Journey] = Field(default_factory=list)
    functional_requirements: list[RequirementItem] = Field(default_factory=list)
    non_functional_requirements: list[NFRItem] = Field(default_factory=list)
    acceptance_metrics: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class TargetEndpoint(StrictModel):
    id: str
    provider: str
    deployment_id: str
    region: str
    modalities: list[str]
    supports_tools: bool
    supports_schema: bool
    context_limit: int = Field(gt=0)
    input_price_per_million: Decimal | None = Field(default=None, ge=0)
    output_price_per_million: Decimal | None = Field(default=None, ge=0)
    rpm: int = Field(gt=0)
    tpm: int = Field(gt=0)


class ModelAlias(StrictModel):
    id: str
    task: str
    endpoint_ids: list[str]
    required_capabilities: list[str] = Field(default_factory=list)
    max_output_tokens: int | None = Field(default=None, gt=0)
    fallback_endpoint_ids: list[str] = Field(default_factory=list)
    quality_gate: str | None = None


class RoutingPolicy(StrictModel):
    eligibility_rules: list[str] = Field(default_factory=list)
    ranking: str = "cost-then-latency among eligible endpoints"
    retry_owner: str = "ai-gateway"
    max_attempts: int = Field(default=2, ge=1, le=6)
    circuit_breaker: str = "closed/open/half-open with a limited probe budget"
    stream_policy: str = "no transparent replay after the first streamed byte"


class Service(StrictModel):
    id: str
    name: str
    kind: str
    region: str | None = None
    owner: str
    responsibilities: list[str] = Field(default_factory=list)
    technology: str | None = None
    scaling: str | None = None
    exposes: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    data_owned: list[str] = Field(default_factory=list)


class DataStore(StrictModel):
    id: str
    name: str
    kind: str
    purpose: str
    region: str
    partition_key: str
    consistency: str
    retention_days: int = Field(gt=0)
    owner_service: str | None = None
    encryption: str | None = None
    backup: str | None = None


class APIContract(StrictModel):
    id: str
    path: str
    method: str
    auth: str
    streaming: bool = False
    summary: str | None = None
    service_id: str | None = None
    scopes: list[str] = Field(default_factory=list)
    rate_limit_rpm: int | None = Field(default=None, gt=0)
    request_fields: list[str] = Field(default_factory=list)
    response_fields: list[str] = Field(default_factory=list)


class GuardrailControl(StrictModel):
    id: str
    stage: str
    control: str
    owner: str
    enforcement: Literal["native", "custom-runtime-required", "design-only"]


class BudgetAllocation(StrictModel):
    scope: str
    share_percent: Decimal = Field(ge=0, le=100)
    amount: Decimal = Field(ge=0)


class BudgetPolicy(StrictModel):
    currency: str
    monthly_limit: Decimal = Field(gt=0)
    hard_limit: bool = True
    unavailable_behavior: Literal["reject", "soft-allow"] = "reject"
    hierarchy: list[str] = Field(
        default_factory=lambda: ["organization", "department", "application"]
    )
    allocations: list[BudgetAllocation] = Field(default_factory=list)
    soft_limit_percent: int | None = Field(default=None, ge=1, le=100)
    per_request_token_ceiling: int | None = Field(default=None, gt=0)
    per_workflow_step_ceiling: int | None = Field(default=None, gt=0)
    rationale: str | None = None


class CachePolicy(StrictModel):
    exact_enabled: bool
    semantic_enabled: bool
    namespace_fields: list[str]
    ttl_seconds: int = Field(ge=0)
    semantic_similarity_threshold: Decimal | None = Field(default=None, gt=0, le=1)
    provider_prompt_caching: bool = False
    retrieval_cache_ttl_seconds: int | None = Field(default=None, ge=0)
    bypass_conditions: list[str] = Field(default_factory=list)
    invalidation_events: list[str] = Field(default_factory=list)
    rationale: str | None = None


class QueuePolicy(StrictModel):
    broker: str
    max_attempts: int = Field(gt=0)
    max_age_seconds: int = Field(gt=0)
    dlq_owner: str
    delivery: Literal["at-least-once"] = "at-least-once"


class ResiliencePlan(StrictModel):
    retry_policy: str
    retry_owner: str
    circuit_breaker: str
    timeouts: list[str] = Field(default_factory=list)
    scaling_rules: list[str] = Field(default_factory=list)
    degraded_modes: list[str] = Field(default_factory=list)
    dr_strategy: str
    rto_minutes: int | None = None
    rpo_minutes: int | None = None


class OAuthFlow(StrictModel):
    name: str
    grant_type: str
    client: str
    audience: str
    scopes: list[str] = Field(default_factory=list)
    pkce: bool = False
    token_lifetime_minutes: int | None = Field(default=None, gt=0)
    notes: str | None = None


class RoleDefinition(StrictModel):
    name: str
    description: str
    permissions: list[str] = Field(default_factory=list)


class ServiceIdentity(StrictModel):
    service_id: str
    identity_type: str
    grants: list[str] = Field(default_factory=list)


class IdentityPolicy(StrictModel):
    idp: str
    tenant_mode: Literal["single", "multi"]
    required_claims: list[str]
    object_level_authorization: bool
    tenant_mapping: str | None = None
    oauth_flows: list[OAuthFlow] = Field(default_factory=list)
    roles: list[RoleDefinition] = Field(default_factory=list)
    service_identities: list[ServiceIdentity] = Field(default_factory=list)
    session_management: str | None = None


class Threat(StrictModel):
    id: str
    title: str
    stride: str
    owasp_ref: str | None = None
    severity: Literal["low", "medium", "high", "critical"]
    affected: list[str] = Field(default_factory=list)
    mitigation: str
    owner: str
    residual_risk: Literal["low", "medium", "high"] = "medium"


class MetricSpec(StrictModel):
    name: str
    description: str
    slo: str | None = None
    alert: str | None = None


class ObservabilityPlan(StrictModel):
    tracing: str
    model_analytics: str
    correlation_ids: list[str]
    redaction_required: bool = True
    metrics: list[MetricSpec] = Field(default_factory=list)
    dashboards: list[str] = Field(default_factory=list)
    log_retention_days: int | None = Field(default=None, gt=0)
    sampling: str | None = None
    redaction: str | None = None


class EvalMetric(StrictModel):
    name: str
    target: str
    method: str


class EvalPlan(StrictModel):
    datasets: list[str] = Field(default_factory=list)
    metrics: list[EvalMetric] = Field(default_factory=list)
    cadence: str
    release_gates: list[str] = Field(default_factory=list)
    routes_covered: str = "every primary and fallback route"


class RAGPipeline(StrictModel):
    ingestion_steps: list[str]
    chunking_strategy: str
    chunk_size_tokens: int = Field(gt=0)
    chunk_overlap_tokens: int = Field(ge=0)
    embedding_model_alias: str
    embedding_dimensions: int = Field(gt=0)
    similarity_metric: str
    retrieval_mode: Literal["vector", "keyword", "hybrid"]
    top_k: int = Field(gt=0)
    reranking: str
    grounding_policy: str
    freshness: str
    acl_enforcement: str
    index_version_policy: str = (
        "Changing the embedding model or dimensions requires a new index version and reindex"
    )


class CloudResource(StrictModel):
    name: str
    service: str
    tier: str
    purpose: str


class DeploymentProfile(StrictModel):
    name: Literal["azure-aca", "azure-aks", "aws-eks", "agnostic"]
    hosting_cloud: str
    region: str
    resources: list[str]
    image_reference_required: bool = True
    compute: str | None = None
    environments: list[str] = Field(default_factory=list)
    networking: list[str] = Field(default_factory=list)
    resource_details: list[CloudResource] = Field(default_factory=list)
    iac_notes: list[str] = Field(default_factory=list)


class Workflow(StrictModel):
    id: str
    name: str
    steps: list[str]
    hitl_required: bool
    trigger: str | None = None
    description: str | None = None


class ArchitectureDecision(StrictModel):
    id: str
    component: str
    title: str
    decision: str
    rationale: str
    alternatives: list[str] = Field(default_factory=list)
    consequences: str | None = None
    source: str = "deterministic-baseline"


class VerificationFinding(StrictModel):
    severity: Literal["blocking", "warning", "info"]
    component: str
    issue: str
    recommendation: str
    resolved: bool = False


class ComponentState(StrictModel):
    name: str
    status: ComponentStatus
    revision: int | None = None
    input_hash: str | None = None
    reason: str | None = None
    source: str | None = None


class ExternalDependency(StrictModel):
    id: str
    contract: str
    supplied_by: str
    status: Literal["provided", "missing"]


class ManualDecision(StrictModel):
    component: str
    field_path: str
    value: Any
    provenance: Literal["user_set"] = "user_set"


class DecisionLock(StrictModel):
    component: str
    field_path: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class InvalidationRecord(StrictModel):
    source_component: str
    target_component: str
    reason: str


class ValidationDiagnostic(StrictModel):
    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    component: str | None = None
    field: str | None = None


class Node(StrictModel):
    id: str
    label: str
    kind: str
    lane: str


class Edge(StrictModel):
    id: str
    source: str
    target: str
    label: str
    kind: str = "data"


class ArchitectureGraph(StrictModel):
    nodes: list[Node]
    edges: list[Edge]

    @model_validator(mode="after")
    def no_orphans(self) -> ArchitectureGraph:
        node_ids = {node.id for node in self.nodes}
        for edge in self.edges:
            if edge.source not in node_ids or edge.target not in node_ids:
                raise ValueError(f"edge {edge.id} references an unknown node")
        return self


class CostLineItem(StrictModel):
    name: str
    quantity: Decimal
    unit: str
    unit_price: Decimal | None
    currency: str
    subtotal: Decimal | None
    source: str


class CapacityResult(StrictModel):
    calls_per_minute: Decimal
    input_tokens_per_minute: Decimal
    output_tokens_per_minute: Decimal
    worker_count: int


class CostEstimate(StrictModel):
    scenario: str
    currency: str
    known_subtotal: Decimal
    complete: bool
    items: list[CostLineItem]
    warnings: list[str]


class EnterpriseDesign(StrictModel):
    schema_version: int = 1
    project: str
    requirements: RequirementsSpec
    prd: PRD | None = None
    services: list[Service] = Field(default_factory=list)
    api_contracts: list[APIContract] = Field(default_factory=list)
    data_stores: list[DataStore] = Field(default_factory=list)
    workflows: list[Workflow] = Field(default_factory=list)
    rag_pipeline: RAGPipeline | None = None
    endpoints: list[TargetEndpoint] = Field(default_factory=list)
    model_aliases: list[ModelAlias] = Field(default_factory=list)
    routing_policy: RoutingPolicy | None = None
    budget_policy: BudgetPolicy | None = None
    cache_policy: CachePolicy | None = None
    queue_policy: QueuePolicy | None = None
    resilience: ResiliencePlan | None = None
    identity_policy: IdentityPolicy | None = None
    guardrails: list[GuardrailControl] = Field(default_factory=list)
    observability: ObservabilityPlan | None = None
    eval_plan: EvalPlan | None = None
    deployment: DeploymentProfile | None = None
    capacity: CapacityResult | None = None
    costs: list[CostEstimate] = Field(default_factory=list)
    components: dict[str, ComponentState] = Field(default_factory=dict)
    external_dependencies: list[ExternalDependency] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    threats: list[Threat] = Field(default_factory=list)
    decisions: list[ArchitectureDecision] = Field(default_factory=list)
    verification: list[VerificationFinding] = Field(default_factory=list)
    verification_summary: str | None = None

    @model_validator(mode="after")
    def references_exist(self) -> EnterpriseDesign:
        endpoint_ids = {endpoint.id for endpoint in self.endpoints}
        for alias in self.model_aliases:
            unknown = (set(alias.endpoint_ids) | set(alias.fallback_endpoint_ids)) - endpoint_ids
            if unknown:
                raise ValueError(
                    f"alias {alias.id} references unknown endpoints: {sorted(unknown)}"
                )
        return self


class ProjectMetadata(StrictModel):
    slug: str
    created_at: datetime = Field(default_factory=utc_now)
    latest_revision: int = 0
    latest_complete_revision: int | None = None
    latest_export: str | None = None


class RevisionManifest(StrictModel):
    schema_version: int = 1
    project: str
    revision: int
    created_at: datetime
    selected_scope: list[str]
    design_sha256: str
    scope_valid: bool
    project_complete: bool
    diagnostics: list[ValidationDiagnostic]
    locks: list[DecisionLock]
    manual_decisions: list[ManualDecision]
    run_id: str | None = None


class ArtifactRecord(StrictModel):
    path: str
    sha256: str | None
    status: Literal["generated", "failed", "not_applicable"]
    reason: str | None = None


class ExportBundleManifest(StrictModel):
    schema_version: int = 1
    project: str
    revision: int
    bundle_id: str
    created_at: datetime
    formats: list[str]
    artifacts: list[ArtifactRecord]
    design_sha256: str


class RoleCallRecord(StrictModel):
    role: str
    step: str
    provider: str
    model: str
    status: Literal["ok", "failed", "skipped"]
    seconds: float = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None


class RunState(StrictModel):
    id: str
    project: str
    base_revision: int
    selected_scope: list[str]
    status: Literal["running", "blocked", "failed", "accepted", "cancelled", "interviewing"]
    completed_steps: list[str] = Field(default_factory=list)
    diagnostics: list[ValidationDiagnostic] = Field(default_factory=list)
    architect_provider: str | None = None
    architect_model: str | None = None
    architect_usage: dict[str, int | None] = Field(default_factory=dict)
    design_mode: str | None = None
    role_calls: list[RoleCallRecord] = Field(default_factory=list)
    revision: int | None = None
    created_at: datetime = Field(default_factory=utc_now)
