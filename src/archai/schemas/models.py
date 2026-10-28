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
    assumptions: list[Assumption] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_peak(self) -> RequirementsSpec:
        if self.peak_rps < self.avg_rps:
            raise ValueError("peak_rps must be greater than or equal to avg_rps")
        return self


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


class Service(StrictModel):
    id: str
    name: str
    kind: str
    region: str | None = None
    owner: str


class DataStore(StrictModel):
    id: str
    name: str
    kind: str
    purpose: str
    region: str
    partition_key: str
    consistency: str
    retention_days: int = Field(gt=0)


class APIContract(StrictModel):
    id: str
    path: str
    method: str
    auth: str
    streaming: bool = False


class GuardrailControl(StrictModel):
    id: str
    stage: str
    control: str
    owner: str
    enforcement: Literal["native", "custom-runtime-required", "design-only"]


class BudgetPolicy(StrictModel):
    currency: str
    monthly_limit: Decimal = Field(gt=0)
    hard_limit: bool = True
    unavailable_behavior: Literal["reject", "soft-allow"] = "reject"
    hierarchy: list[str] = Field(
        default_factory=lambda: ["organization", "department", "application"]
    )


class CachePolicy(StrictModel):
    exact_enabled: bool
    semantic_enabled: bool
    namespace_fields: list[str]
    ttl_seconds: int = Field(ge=0)


class QueuePolicy(StrictModel):
    broker: str
    max_attempts: int = Field(gt=0)
    max_age_seconds: int = Field(gt=0)
    dlq_owner: str
    delivery: Literal["at-least-once"] = "at-least-once"


class IdentityPolicy(StrictModel):
    idp: str
    tenant_mode: Literal["single", "multi"]
    required_claims: list[str]
    object_level_authorization: bool


class ObservabilityPlan(StrictModel):
    tracing: str
    model_analytics: str
    correlation_ids: list[str]
    redaction_required: bool = True


class DeploymentProfile(StrictModel):
    name: Literal["azure-aca", "azure-aks", "aws-eks", "agnostic"]
    hosting_cloud: str
    region: str
    resources: list[str]
    image_reference_required: bool = True


class Workflow(StrictModel):
    id: str
    name: str
    steps: list[str]
    hitl_required: bool


class ComponentState(StrictModel):
    name: str
    status: ComponentStatus
    revision: int | None = None
    input_hash: str | None = None
    reason: str | None = None


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
    services: list[Service] = Field(default_factory=list)
    api_contracts: list[APIContract] = Field(default_factory=list)
    data_stores: list[DataStore] = Field(default_factory=list)
    workflows: list[Workflow] = Field(default_factory=list)
    endpoints: list[TargetEndpoint] = Field(default_factory=list)
    model_aliases: list[ModelAlias] = Field(default_factory=list)
    budget_policy: BudgetPolicy | None = None
    cache_policy: CachePolicy | None = None
    queue_policy: QueuePolicy | None = None
    identity_policy: IdentityPolicy | None = None
    guardrails: list[GuardrailControl] = Field(default_factory=list)
    observability: ObservabilityPlan | None = None
    deployment: DeploymentProfile | None = None
    capacity: CapacityResult | None = None
    costs: list[CostEstimate] = Field(default_factory=list)
    components: dict[str, ComponentState] = Field(default_factory=dict)
    external_dependencies: list[ExternalDependency] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_exist(self) -> EnterpriseDesign:
        endpoint_ids = {endpoint.id for endpoint in self.endpoints}
        for alias in self.model_aliases:
            unknown = set(alias.endpoint_ids) - endpoint_ids
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


class RunState(StrictModel):
    id: str
    project: str
    base_revision: int
    selected_scope: list[str]
    status: Literal["running", "blocked", "failed", "accepted", "cancelled"]
    completed_steps: list[str] = Field(default_factory=list)
    diagnostics: list[ValidationDiagnostic] = Field(default_factory=list)
