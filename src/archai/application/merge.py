"""Validate architect-model proposals and merge them into canonical state.

Model output is a proposal. This module normalizes IDs, drops dangling references, clamps numeric
values, and enforces policy invariants that pure Python code owns.
"""

from __future__ import annotations

import re
from decimal import Decimal
from functools import cache
from importlib.resources import files
from typing import Any, get_origin

import yaml
from pydantic import BaseModel

from archai.application import designer
from archai.application.derive import derive_all
from archai.application.designer import (
    REQUIRED_CACHE_NAMESPACE,
    REQUIRED_CLAIMS,
    REQUIRED_CORRELATION_IDS,
    add_decision,
    align_fixed_facts,
    attach_recovery_endpoints,
    compute_allocations,
    ensure_approval_operations,
    has_rag,
    proposed_endpoint,
    recovery_strategy,
    regions_outside,
    slug_id,
    target_endpoints,
    uses_tools,
)
from archai.schemas.models import (
    APIContract,
    BudgetAllocation,
    BudgetPolicy,
    CachePolicy,
    CloudResource,
    ComponentStatus,
    DataStore,
    DeploymentProfile,
    EnterpriseDesign,
    EvalMetric,
    EvalPlan,
    GuardrailControl,
    IdentityPolicy,
    MetricSpec,
    ModelAlias,
    OAuthFlow,
    ObservabilityPlan,
    QueuePolicy,
    RAGPipeline,
    ResiliencePlan,
    RoleDefinition,
    RoutingPolicy,
    Service,
    ServiceIdentity,
    Threat,
    ValidationDiagnostic,
    Workflow,
)
from archai.schemas.proposals import (
    APIContractProposal,
    DataStoreProposal,
    GuardrailProposal,
    ServiceProposal,
    ThreatProposal,
    WorkflowProposal,
)

OWNER_BY_KIND = {
    "frontend": "application",
    "gateway": "platform",
    "application": "application",
    "orchestration": "application",
    "policy": "ai-platform",
    "ai-gateway": "ai-platform",
    "retrieval": "application",
    "ingestion": "data-platform",
    "worker": "application",
    "tool-executor": "application",
    "integration": "application",
    "operations": "operations",
}
REQUIRED_SERVICE_KINDS = (
    ("gateway",),
    ("application", "orchestration"),
    ("policy",),
    ("ai-gateway",),
)
VECTOR_WORDS = ("search", "vector", "opensearch", "qdrant", "pinecone", "pgvector", "index")


@cache
def owasp_ids() -> frozenset[str]:
    text = files("archai.resources.catalogs").joinpath("owasp_llm_2025.yaml").read_text()
    data = yaml.safe_load(text)
    return frozenset(str(item["id"]) for item in data.get("entries", []))


def _diag(code: str, message: str, component: str, severity: str = "info") -> ValidationDiagnostic:
    return ValidationDiagnostic(
        code=code,
        severity=severity,
        message=message,
        component=component,
    )


def _clamp(value: int | float, low: int | float, high: int | float) -> Any:
    return max(low, min(high, value))


CAPABILITY_WORDS = {
    "embedding": "embeddings",
    "stream": "streaming",
    "schema": "json-schema",
    "structured": "json-schema",
    "json": "json-schema",
    "tool": "tools",
    "function": "tools",
    "vision": "vision",
    "image": "vision",
    "audio": "audio",
    "speech": "audio",
    "long": "long-context",
    "text": "text",
    "chat": "text",
    "generation": "text",
}


def _capabilities(values: list[str]) -> list[str]:
    """Map free-text capability phrases to the canonical capability vocabulary."""
    result: list[str] = []
    for value in values:
        lowered = value.lower()
        for word, capability in CAPABILITY_WORDS.items():
            if word in lowered and capability not in result:
                result.append(capability)
    return result or ["text"]


def _clean(values: list[str], limit: int = 12) -> list[str]:
    seen: list[str] = []
    for item in values:
        text = str(item).strip()
        if text and text not in seen:
            seen.append(text)
    return seen[:limit]


# Components whose content is a list of items with ids. A repair (patch mode) returns only the
# items it adds or changes; the others are kept, and remove_ids deletes items by id.
PATCH_LISTS: dict[str, tuple[str, type[BaseModel], str]] = {
    "system": ("services", ServiceProposal, "svc-"),
    "data": ("data_stores", DataStoreProposal, "store-"),
    "workflow": ("workflows", WorkflowProposal, "workflow-"),
    "api": ("api_contracts", APIContractProposal, "api-"),
    "guard": ("guardrails", GuardrailProposal, "guard-"),
    "security": ("threats", ThreatProposal, "threat-"),
}


def _as_proposal(item: BaseModel, kind: type[BaseModel]) -> Any:
    """Re-express a stored item as the proposal it would have come from, for re-merging."""
    data = item.model_dump()
    values: dict[str, Any] = {}
    for name, info in kind.model_fields.items():
        value = data.get(name)
        if value is None:
            if get_origin(info.annotation) is list:
                value = []
            elif info.annotation is int:
                value = 0
            elif info.annotation is bool:
                value = False
            else:
                value = ""
        values[name] = value
    return kind.model_construct(**values)


def _item_key(item: Any, prefix: str) -> str:
    if prefix == "api-":
        raw = item.id or f"{item.method}-{item.path}"
    elif prefix == "guard-":
        raw = item.id or f"{item.stage}-{item.control}"
    elif prefix == "threat-":
        raw = item.id or item.title
    else:
        raw = item.id or item.name
    return slug_id(raw, prefix)


class ProposalMerger:
    """Merge one role proposal; ``aliases`` maps proposed IDs to normalized canonical IDs.

    In patch mode (repairs), list components and decisions are edited in place: returned items
    replace the items with the same id, other items are kept, and ``remove_ids`` deletes items.
    """

    def __init__(self, design: EnterpriseDesign, source: str, patch: bool = False) -> None:
        self.design = design
        self.req = design.requirements
        self.source = source
        self.patch = patch
        self.aliases: dict[str, str] = {}
        self.diagnostics: list[ValidationDiagnostic] = []

    # ------------------------------------------------------------------ entry point

    def merge(self, proposal: BaseModel, components: list[str]) -> list[ValidationDiagnostic]:
        ordered = [
            "data",
            "system",
            "workflow",
            "rag",
            "infra",
            "resilience",
            "routing",
            "api",
            "budget",
            "cache",
            "auth",
            "guard",
            "security",
            "observe",
            "eval",
        ]
        handlers = {
            "data": ("data_stores", self.data_stores),
            "system": ("services", self.services),
            "workflow": ("workflows", self.workflows),
            "rag": ("rag", self.rag),
            "infra": ("infra", self.infra),
            "resilience": ("resilience", self.resilience),
            "routing": ("routing", self.routing),
            "api": ("api_contracts", self.api),
            "budget": ("budget", self.budget),
            "cache": ("cache", self.cache_policy),
            "auth": ("identity", self.identity),
            "guard": ("guardrails", self.guardrails),
            "security": ("threats", self.threats),
            "observe": ("observability", self.observability),
            "eval": ("evaluation", self.evaluation),
        }
        merged: list[str] = []
        removals = [str(item) for item in getattr(proposal, "remove_ids", []) or []]
        for component in ordered:
            if component not in components or component not in handlers:
                continue
            field, handler = handlers[component]
            value = getattr(proposal, field, None)
            if value is None:
                continue
            if self.patch and component in PATCH_LISTS:
                value = self._patched(component, value, removals)
            handler(value, proposal)
            state = self.design.components.get(component)
            if state is not None and state.status == ComponentStatus.valid:
                state.source = self.source
            merged.append(component)
        self.decisions(getattr(proposal, "decisions", []) or [], merged, removals)
        return self.diagnostics

    def _bounded(
        self,
        value: Any,
        default: int | float,
        low: int | float,
        high: int | float,
        label: str,
        component: str,
        meaning: str = "",
    ) -> Any:
        """Keep a proposed number in range, and tell the role when its value was changed."""
        proposed = value if value else default
        result = _clamp(proposed, low, high)
        if value and result != proposed:
            note = f" ({meaning})" if meaning else ""
            self.diagnostics.append(
                _diag(
                    "LIMIT_REJECTED",
                    f"{label} {proposed} is outside {low}–{high}{note}; ArchAI used {result}",
                    component,
                    "warning",
                )
            )
        return result

    def _patched(self, component: str, returned: list[Any], removals: list[str]) -> list[Any]:
        design_field, kind, prefix = PATCH_LISTS[component]
        current = [_as_proposal(item, kind) for item in getattr(self.design, design_field)]
        removed = {slug_id(item, prefix) for item in removals} | {item.lower() for item in removals}
        by_key: dict[str, Any] = {}
        for item in [*current, *returned]:
            by_key[_item_key(item, prefix)] = item
        return [item for key, item in by_key.items() if key not in removed]

    # ------------------------------------------------------------------ cloud, data, resilience

    def data_stores(self, items: list[Any], proposal: BaseModel) -> None:
        del proposal
        stores: list[DataStore] = []
        for item in items[:10]:
            identifier = slug_id(item.id or item.name, "store-")
            if any(store.id == identifier for store in stores):
                continue
            self.aliases[str(item.id).lower()] = identifier
            stores.append(
                DataStore(
                    id=identifier,
                    name=item.name.strip() or identifier,
                    kind=item.kind.strip() or "managed data store",
                    purpose=item.purpose.strip() or "application data",
                    region=self.req.region,
                    partition_key=item.partition_key.strip() or "tenant_id",
                    consistency=item.consistency.strip() or "strong",
                    retention_days=int(
                        self._bounded(
                            item.retention_days,
                            365,
                            1,
                            3650,
                            f"{identifier}.retention_days",
                            "data",
                            "days",
                        )
                    ),
                    owner_service=item.owner_service or None,
                    encryption=item.encryption or "encryption at rest and in transit",
                    backup=item.backup or None,
                )
            )
        text = " ".join(f"{s.id} {s.name} {s.purpose}".lower() for s in stores)
        baseline = _baseline_stores(self.design)
        if "ledger" not in text and "budget" not in text:
            stores.append(baseline["store-ledger"])
            self.diagnostics.append(
                _diag(
                    "MERGE_ADDED_LEDGER",
                    "Added the transactional budget ledger required by hard budgets",
                    "data",
                )
            )
        if has_rag(self.req) and not any(
            word in f"{s.kind} {s.name}".lower() for s in stores for word in VECTOR_WORDS
        ):
            stores.append(baseline["store-vector"])
            self.diagnostics.append(
                _diag("MERGE_ADDED_VECTOR", "Added a managed vector index for retrieval", "data")
            )
        self.design.data_stores = stores

    def services(self, items: list[Any], proposal: BaseModel) -> None:
        del proposal
        services: list[Service] = []
        for item in items[:16]:
            identifier = slug_id(item.id or item.name, "svc-")
            if any(service.id == identifier for service in services):
                continue
            self.aliases[str(item.id).lower()] = identifier
            services.append(
                Service(
                    id=identifier,
                    name=item.name.strip() or identifier,
                    kind=item.kind,
                    region=self.req.region,
                    owner=OWNER_BY_KIND.get(item.kind, "application"),
                    responsibilities=_clean(item.responsibilities, 8),
                    technology=item.technology or None,
                    scaling=item.scaling or None,
                    exposes=_clean(item.exposes, 10),
                    depends_on=[str(value) for value in item.depends_on],
                    data_owned=[str(value) for value in item.data_owned],
                )
            )
        baseline = _baseline_services(self.design)
        added: list[Service] = []
        for kinds in REQUIRED_SERVICE_KINDS:
            if not any(service.kind in kinds for service in services):
                addition = next(service for service in baseline if service.kind == kinds[0])
                services.append(addition)
                added.append(addition)
                self.diagnostics.append(
                    _diag(
                        "MERGE_ADDED_SERVICE",
                        f"Added required {kinds[0]} service '{addition.name}'",
                        "system",
                    )
                )
        _wire_additions(services, added, baseline)
        self.design.services = services

    def workflows(self, items: list[Any], proposal: BaseModel) -> None:
        del proposal
        workflows: list[Workflow] = []
        for item in items[:8]:
            identifier = slug_id(item.id or item.name, "workflow-")
            if any(workflow.id == identifier for workflow in workflows):
                continue
            steps = _clean(item.steps, 14)
            if not steps:
                continue
            workflows.append(
                Workflow(
                    id=identifier,
                    name=item.name.strip() or identifier,
                    trigger=item.trigger or None,
                    description=item.description or None,
                    steps=steps,
                    hitl_required=bool(item.hitl_required),
                )
            )
        if not workflows:
            designer.baseline_component(self.design, "workflow")
            return
        self.design.workflows = workflows

    def rag(self, item: Any, proposal: BaseModel) -> None:
        del proposal
        if not has_rag(self.req):
            return
        embedding = next(
            (
                alias.id
                for alias in self.design.model_aliases
                if "embeddings" in alias.required_capabilities
            ),
            slug_id(item.embedding_model_alias or "enterprise-embedding", ""),
        )
        size = int(
            self._bounded(
                item.chunk_size_tokens,
                800,
                100,
                8000,
                "rag.chunk_size_tokens",
                "rag",
                "tokens per chunk",
            )
        )
        self.design.rag_pipeline = RAGPipeline(
            ingestion_steps=_clean(item.ingestion_steps, 12)
            or ["parse", "chunk", "embed", "index"],
            chunking_strategy=item.chunking_strategy or "structure-aware",
            chunk_size_tokens=size,
            chunk_overlap_tokens=int(_clamp(item.chunk_overlap_tokens or 0, 0, size // 2)),
            embedding_model_alias=embedding,
            embedding_dimensions=int(
                self._bounded(
                    item.embedding_dimensions, 1536, 64, 8192, "rag.embedding_dimensions", "rag"
                )
            ),
            similarity_metric=item.similarity_metric or "cosine",
            retrieval_mode=item.retrieval_mode,
            top_k=int(
                self._bounded(
                    item.top_k, 8, 1, 50, "rag.top_k", "rag", "passages retrieved per query"
                )
            ),
            reranking=item.reranking or "none",
            grounding_policy=item.grounding_policy or "cite retrieved sources",
            freshness=item.freshness or "incremental sync",
            acl_enforcement=item.acl_enforcement
            or "security-trimmed filters on tenant and principal groups",
        )

    def infra(self, item: Any, proposal: BaseModel) -> None:
        del proposal
        designer.baseline_component(self.design, "infra")
        baseline = self.design.deployment
        assert baseline is not None
        resources = [
            CloudResource(
                name=slug_id(resource.name or resource.service, ""),
                service=resource.service,
                tier=resource.tier or "-",
                purpose=resource.purpose or "-",
            )
            for resource in item.resources[:24]
            if resource.service.strip()
        ]
        self.design.deployment = DeploymentProfile(
            name=self.req.profile,
            hosting_cloud=baseline.hosting_cloud,
            region=self.req.region,
            resources=baseline.resources,
            compute=item.compute or baseline.compute,
            environments=_clean(item.environments, 6) or baseline.environments,
            networking=_clean(item.networking, 12) or baseline.networking,
            resource_details=resources or baseline.resource_details,
            iac_notes=_clean([*baseline.iac_notes, *item.iac_notes], 10),
        )

    def resilience(self, item: Any, proposal: BaseModel) -> None:
        del proposal
        designer.baseline_component(self.design, "resilience")
        broker = self.design.queue_policy.broker if self.design.queue_policy else "managed broker"
        self.design.queue_policy = QueuePolicy(
            broker=broker,
            max_attempts=int(
                self._bounded(
                    item.max_attempts,
                    5,
                    1,
                    20,
                    "queue_policy.max_attempts",
                    "resilience",
                    "queue deliveries per job",
                )
            ),
            max_age_seconds=int(
                self._bounded(
                    item.max_age_seconds,
                    3600,
                    60,
                    1_209_600,
                    "queue_policy.max_age_seconds",
                    "resilience",
                    "seconds",
                )
            ),
            dlq_owner=item.dlq_owner or "operations",
        )
        self.design.resilience = ResiliencePlan(
            retry_policy=item.retry_policy,
            retry_owner=item.retry_owner or "ai-gateway",
            circuit_breaker=item.circuit_breaker,
            timeouts=_clean(item.timeouts, 10),
            scaling_rules=_clean(item.scaling_rules, 10),
            degraded_modes=_clean(item.degraded_modes, 10),
            dr_strategy=item.dr_strategy,
            rto_minutes=self.req.rto_minutes,
            rpo_minutes=self.req.rpo_minutes,
        )

    # ------------------------------------------------------------------ API, routing, budgets

    def routing(self, item: Any, proposal: BaseModel) -> None:
        self.design.endpoints = target_endpoints(self.req)
        for requested in getattr(proposal, "endpoints", [])[:8]:
            endpoint, reason = proposed_endpoint(self.req, self.design.endpoints, requested)
            if endpoint is not None:
                self.design.endpoints.append(endpoint)
                self.diagnostics.append(
                    _diag(
                        "ENDPOINT_ADDED",
                        f"Added {endpoint.id} ({endpoint.deployment_role}, {endpoint.region}) "
                        f"as proposed: {requested.reason[:160]}",
                        "routing",
                    )
                )
            elif reason is not None:
                self.diagnostics.append(
                    _diag(
                        "ENDPOINT_REJECTED",
                        f"Did not add a {requested.purpose} deployment of {requested.provider} "
                        f"in {requested.region}: {reason}",
                        "routing",
                        "warning",
                    )
                )
        serving = [e for e in self.design.endpoints if e.deployment_role == "primary"]
        chat = [e for e in serving if "embeddings" not in e.modalities]
        embedding = [e for e in serving if "embeddings" in e.modalities]

        def endpoint_for(provider: str) -> str | None:
            wanted = provider.lower().replace("-", " ")
            for endpoint in chat:
                name = endpoint.provider.lower()
                if wanted in name or name in wanted:
                    return endpoint.id
            return None

        aliases: list[ModelAlias] = []
        for alias in getattr(proposal, "model_aliases", [])[:8]:
            identifier = slug_id(alias.id or alias.task, "")
            if any(existing.id == identifier for existing in aliases):
                continue
            capabilities = _capabilities(alias.required_capabilities)
            if "embeddings" in capabilities or "embedding" in identifier:
                if not embedding:
                    continue
                aliases.append(
                    ModelAlias(
                        id=identifier,
                        task=alias.task,
                        endpoint_ids=[embedding[0].id],
                        required_capabilities=["embeddings"],
                        quality_gate=alias.quality_gate or None,
                    )
                )
                continue
            primary = endpoint_for(alias.primary_provider) or (chat[0].id if chat else None)
            if primary is None:
                continue
            fallbacks: list[str] = []
            for provider in alias.fallback_providers:
                candidate = endpoint_for(provider)
                if candidate is None:
                    self.diagnostics.append(
                        _diag(
                            "ROUTE_PROVIDER_NOT_ALLOWED",
                            f"Dropped fallback provider '{provider}' for {identifier}: not an "
                            "allowed target provider",
                            "routing",
                            "warning",
                        )
                    )
                elif candidate != primary and candidate not in fallbacks:
                    fallbacks.append(candidate)
            if self.req.topology == "single-cloud" and fallbacks:
                self.diagnostics.append(
                    _diag(
                        "ROUTE_FALLBACK_TOPOLOGY",
                        f"Removed cross-provider fallback for {identifier}: topology is "
                        "single-cloud",
                        "routing",
                    )
                )
                fallbacks = []
            aliases.append(
                ModelAlias(
                    id=identifier,
                    task=alias.task,
                    endpoint_ids=[primary, *fallbacks],
                    required_capabilities=capabilities,
                    max_output_tokens=int(
                        self._bounded(
                            alias.max_output_tokens,
                            1024,
                            64,
                            65_536,
                            f"{identifier}.max_output_tokens",
                            "routing",
                        )
                    ),
                    fallback_endpoint_ids=fallbacks,
                    quality_gate=alias.quality_gate or None,
                )
            )
        if self.req.topology != "single-cloud" and len(chat) > 1:
            for alias in aliases:
                if "embeddings" in alias.required_capabilities or alias.fallback_endpoint_ids:
                    continue
                extra = [e.id for e in chat if e.id not in alias.endpoint_ids]
                if extra:
                    alias.fallback_endpoint_ids = extra[:1]
                    alias.endpoint_ids = [*alias.endpoint_ids, *extra[:1]]
                    self.diagnostics.append(
                        _diag(
                            "ROUTE_FALLBACK_ADDED",
                            f"{alias.id}: added approved fallback {extra[0]} required by the "
                            f"{self.req.topology} topology (eligibility still applies per request)",
                            "routing",
                        )
                    )
                break
        if not any("embeddings" not in alias.required_capabilities for alias in aliases):
            designer.baseline_component(self.design, "routing")
            aliases = [
                *self.design.model_aliases,
                *[a for a in aliases if a.id != "enterprise-chat"],
            ]
        if embedding and not any("embeddings" in a.required_capabilities for a in aliases):
            aliases.append(
                ModelAlias(
                    id="enterprise-embedding",
                    task="document and query embeddings for one index version",
                    endpoint_ids=[embedding[0].id],
                    required_capabilities=["embeddings"],
                )
            )
        self.design.model_aliases = aliases
        self.design.routing_policy = RoutingPolicy(
            eligibility_rules=_clean(item.eligibility_rules, 10),
            ranking=item.ranking or "cost-then-latency among eligible endpoints",
            retry_owner=item.retry_owner or "ai-gateway",
            max_attempts=int(_clamp(item.max_attempts or 2, 1, 4)),
            circuit_breaker=item.circuit_breaker or "closed/open/half-open",
            stream_policy=item.stream_policy or "no transparent replay after the first byte",
        )

    def api(self, items: list[Any], proposal: BaseModel) -> None:
        del proposal
        auth = (
            f"OIDC bearer token ({self.req.identity_provider})"
            if self.req.identity_provider
            else "not specified (identity not selected)"
        )
        default_service = next(
            (s.id for s in self.design.services if s.kind in {"application", "orchestration"}),
            None,
        )
        service_ids = {service.id for service in self.design.services}
        contracts: list[APIContract] = []
        for item in items[:24]:
            path = "/" + item.path.strip().lstrip("/")
            identifier = slug_id(item.id or f"{item.method}-{path}", "api-")
            if any(c.id == identifier for c in contracts):
                continue
            service_id = self.aliases.get(item.service_id.lower(), item.service_id)
            if service_id not in service_ids:
                service_id = default_service
            contracts.append(
                APIContract(
                    id=identifier,
                    path=path,
                    method=item.method.upper(),
                    auth=(getattr(item, "auth", "") or "").strip()[:200] or auth,
                    streaming=bool(item.streaming),
                    summary=item.summary or None,
                    service_id=service_id,
                    scopes=_clean(item.scopes, 6),
                    rate_limit_rpm=int(
                        self._bounded(
                            item.rate_limit_rpm,
                            600,
                            1,
                            1_000_000,
                            f"{identifier}.rate_limit_rpm",
                            "api",
                            "requests per minute per principal",
                        )
                    ),
                    request_fields=_clean(item.request_fields, 12),
                    response_fields=_clean(item.response_fields, 12),
                )
            )
        if not contracts:
            designer.baseline_component(self.design, "api")
            return
        self.design.api_contracts = contracts

    def budget(self, item: Any, proposal: BaseModel) -> None:
        del proposal
        allocations = [
            BudgetAllocation(
                scope=allocation.scope.strip()[:80] or "application",
                share_percent=Decimal(str(_clamp(allocation.share_percent, 0, 100))).quantize(
                    Decimal("0.01")
                ),
                amount=Decimal(0),
            )
            for allocation in item.allocations[:12]
        ]
        policy = BudgetPolicy(
            currency=self.req.currency,
            monthly_limit=self.req.monthly_budget,
            hard_limit=True,
            unavailable_behavior="reject",
            enforcement_scope="model-calls",
            allocations=allocations,
            soft_limit_percent=int(
                self._bounded(
                    item.soft_limit_percent,
                    80,
                    50,
                    100,
                    "budget_policy.soft_limit_percent",
                    "budget",
                    "percent of the hard limit",
                )
            ),
            per_request_token_ceiling=int(
                self._bounded(
                    item.per_request_token_ceiling,
                    20_000,
                    256,
                    2_000_000,
                    "budget_policy.per_request_token_ceiling",
                    "budget",
                    "tokens one request may use across its calls and attempts",
                )
            ),
            per_workflow_step_ceiling=int(
                self._bounded(
                    item.per_workflow_step_ceiling,
                    12,
                    1,
                    200,
                    "budget_policy.per_workflow_step_ceiling",
                    "budget",
                    "the number of model-calling steps one workflow run may take, not tokens",
                )
            ),
            rationale=item.rationale or None,
        )
        total = sum((a.share_percent for a in allocations), Decimal(0))
        if total > 100:
            self.diagnostics.append(
                _diag(
                    "BUDGET_SHARES_NORMALIZED",
                    f"Budget shares summed to {total}%; normalized to 100%",
                    "budget",
                    "warning",
                )
            )
        compute_allocations(policy)
        self.design.budget_policy = policy

    def cache_policy(self, item: Any, proposal: BaseModel) -> None:
        del proposal
        semantic = bool(item.semantic_enabled)
        if semantic and self.req.data_classification == "restricted":
            semantic = False
            self.diagnostics.append(
                _diag(
                    "CACHE_SEMANTIC_DISABLED",
                    "Semantic caching disabled for restricted data classification",
                    "cache",
                    "warning",
                )
            )
        threshold = Decimal(str(_clamp(item.semantic_similarity_threshold or 0.95, 0.8, 0.999)))
        self.design.cache_policy = CachePolicy(
            exact_enabled=bool(item.exact_enabled),
            semantic_enabled=semantic,
            namespace_fields=list(REQUIRED_CACHE_NAMESPACE),
            ttl_seconds=int(
                self._bounded(
                    item.ttl_seconds, 300, 0, 86_400, "cache_policy.ttl_seconds", "cache", "seconds"
                )
            ),
            semantic_similarity_threshold=threshold.quantize(Decimal("0.001"))
            if semantic
            else None,
            provider_prompt_caching=bool(item.provider_prompt_caching),
            retrieval_cache_ttl_seconds=int(_clamp(item.retrieval_cache_ttl_seconds, 0, 86_400))
            if has_rag(self.req)
            else None,
            bypass_conditions=_clean(item.bypass_conditions, 10),
            invalidation_events=_clean(item.invalidation_events, 10),
            rationale=item.rationale or None,
        )

    # ------------------------------------------------------------------ identity and security

    def identity(self, item: Any, proposal: BaseModel) -> None:
        del proposal
        provider = self.req.identity_provider
        if not provider:
            self.design.identity_policy = None
            return
        flows = [
            OAuthFlow(
                name=flow.name.strip() or flow.grant_type,
                grant_type=flow.grant_type,
                client=flow.client or "client",
                audience=flow.audience or f"api://{self.design.project}",
                scopes=_clean(flow.scopes, 10),
                pkce=flow.grant_type == "authorization_code_pkce",
                token_lifetime_minutes=int(
                    self._bounded(
                        flow.token_lifetime_minutes,
                        60,
                        5,
                        1440,
                        f"{flow.name}.token_lifetime_minutes",
                        "auth",
                        "minutes",
                    )
                ),
                notes=flow.notes or None,
            )
            for flow in item.oauth_flows[:8]
        ]
        designer.baseline_component(self.design, "auth")
        baseline = self.design.identity_policy
        assert baseline is not None
        grants = {flow.grant_type for flow in flows}
        for flow in baseline.oauth_flows:
            if flow.grant_type in {"authorization_code_pkce", "client_credentials"} and (
                flow.grant_type not in grants
            ):
                flows.append(flow)
                self.diagnostics.append(
                    _diag(
                        "AUTH_FLOW_ADDED",
                        f"Added required OAuth flow '{flow.name}' ({flow.grant_type})",
                        "auth",
                    )
                )
        roles = [
            RoleDefinition(
                name=role.name.strip(),
                description=role.description,
                permissions=_clean(role.permissions, 16),
            )
            for role in item.roles[:12]
            if role.name.strip()
        ]
        names = {role.name.lower() for role in roles}
        requested = {name.lower() for name in self.req.user_roles}
        roles.extend(
            role
            for role in baseline.roles
            if role.name.lower() not in names and (not roles or role.name.lower() in requested)
        )
        service_ids = {service.id for service in self.design.services}
        identities = []
        for identity in item.service_identities[:16]:
            service_id = self.aliases.get(identity.service_id.lower(), identity.service_id)
            if service_id in service_ids:
                identities.append(
                    ServiceIdentity(
                        service_id=service_id,
                        identity_type=identity.identity_type,
                        grants=_clean(identity.grants, 10),
                    )
                )
        self.design.identity_policy = IdentityPolicy(
            idp=provider,
            tenant_mode=self.req.tenant_isolation,
            required_claims=_clean([*REQUIRED_CLAIMS, *item.extra_required_claims], 16),
            object_level_authorization=True,
            tenant_mapping=item.tenant_mapping or baseline.tenant_mapping,
            oauth_flows=flows,
            roles=roles,
            service_identities=identities or baseline.service_identities,
            session_management=item.session_management or baseline.session_management,
        )

    def guardrails(self, items: list[Any], proposal: BaseModel) -> None:
        del proposal
        controls: list[GuardrailControl] = []
        for item in items[:20]:
            identifier = slug_id(item.id or f"{item.stage}-{item.control}", "guard-")
            if any(control.id == identifier for control in controls):
                continue
            controls.append(
                GuardrailControl(
                    id=identifier,
                    stage=item.stage,
                    control=item.control,
                    owner=item.owner or "application",
                    enforcement=item.enforcement,
                )
            )
        required = {"input", "output"}
        if uses_tools(self.req):
            required.add("tool")
        if has_rag(self.req):
            required.add("retrieval")
        present = {control.stage for control in controls}
        if required - present:
            designer.baseline_component(self.design, "guard")
            for control in self.design.guardrails:
                if control.stage in required - present:
                    controls.append(control)
                    self.diagnostics.append(
                        _diag(
                            "GUARD_STAGE_ADDED",
                            f"Added required {control.stage} guardrail '{control.id}'",
                            "guard",
                        )
                    )
        if self.req.tool_side_effects == "forbidden" and not any(
            control.id == "guard-no-side-effects" for control in controls
        ):
            controls.append(
                GuardrailControl(
                    id="guard-no-side-effects",
                    stage="execution",
                    control="read-only tool credentials; state-changing tools are not registered",
                    owner="platform",
                    enforcement="custom-runtime-required",
                )
            )
        self.design.guardrails = controls

    def threats(self, items: list[Any], proposal: BaseModel) -> None:
        del proposal
        valid = owasp_ids()
        threats: list[Threat] = []
        for item in items[:24]:
            identifier = slug_id(item.id or item.title, "threat-")
            if any(threat.id == identifier for threat in threats):
                continue
            found = re.search(r"LLM\s?(\d{2})\s?:\s?2025", item.owasp_ref or "", re.IGNORECASE)
            reference = f"LLM{found.group(1)}:2025" if found else (item.owasp_ref.strip() or None)
            if reference and reference not in valid:
                self.diagnostics.append(
                    _diag(
                        "OWASP_REF_UNKNOWN",
                        f"Removed unverified OWASP reference '{reference}' from {identifier}",
                        "security",
                    )
                )
                reference = None
            threats.append(
                Threat(
                    id=identifier,
                    title=item.title,
                    stride=item.stride,
                    owasp_ref=reference,
                    severity=item.severity,
                    affected=[
                        self.aliases.get(str(value).lower(), str(value))
                        for value in item.affected[:8]
                    ],
                    mitigation=item.mitigation,
                    owner=item.owner or "security",
                    residual_risk=item.residual_risk,
                )
            )
        if not threats:
            designer.baseline_component(self.design, "security")
            return
        designer.baseline_component(self.design, "security")
        self.design.threats = threats

    def observability(self, item: Any, proposal: BaseModel) -> None:
        del proposal
        self.design.observability = ObservabilityPlan(
            tracing=item.tracing or "OpenTelemetry",
            model_analytics=item.model_analytics or "Langfuse",
            correlation_ids=_clean([*REQUIRED_CORRELATION_IDS, *item.extra_correlation_ids], 16),
            redaction_required=True,
            metrics=[
                MetricSpec(
                    name=metric.name,
                    description=metric.description,
                    slo=metric.slo or None,
                    alert=metric.alert or None,
                )
                for metric in item.metrics[:20]
            ],
            dashboards=_clean(item.dashboards, 10),
            log_retention_days=int(
                self._bounded(
                    item.log_retention_days,
                    90,
                    1,
                    3650,
                    "observability.log_retention_days",
                    "observe",
                    "days",
                )
            ),
            sampling=item.sampling or None,
            redaction=item.redaction or None,
        )

    def evaluation(self, item: Any, proposal: BaseModel) -> None:
        del proposal
        self.design.eval_plan = EvalPlan(
            datasets=_clean(item.datasets, 10),
            metrics=[
                EvalMetric(name=metric.name, target=metric.target, method=metric.method)
                for metric in item.metrics[:16]
            ],
            cadence=item.cadence or "on every model, prompt, or index change",
            release_gates=_clean(item.release_gates, 10),
            routes_covered=item.routes_covered or "every primary and fallback route",
        )

    def decisions(
        self, items: list[Any], merged: list[str], removals: list[str] | None = None
    ) -> None:
        if not merged:
            return
        if self.patch and removals:
            removed = {item.lower() for item in removals}
            self.design.decisions = [
                item
                for item in self.design.decisions
                if item.id.lower() not in removed or item.source == designer.FIXED_SOURCE
            ]
        grouped: dict[str, list[Any]] = {}
        for item in items[:30]:
            component = item.component if item.component in merged else merged[0]
            grouped.setdefault(component, []).append(item)
        for component, decisions in grouped.items():
            if not self.patch:
                designer.replace_component_decisions(self.design, component)
            for item in decisions[:4]:
                add_decision(
                    self.design,
                    component,
                    item.title,
                    item.decision,
                    item.rationale,
                    _clean(item.alternatives, 5),
                    item.consequences or None,
                    source=self.source,
                )


def _kind_group(kind: str) -> tuple[str, ...]:
    return next((kinds for kinds in REQUIRED_SERVICE_KINDS if kind in kinds), (kind,))


def _wire_additions(services: list[Service], added: list[Service], template: list[Service]) -> None:
    """Connect platform services Python added the way its template connects them.

    The template's ids are mapped to the services of the same kind in this design, so an added
    gateway calls the role's application service rather than a template id that is not there.
    """
    if not added:
        return
    kinds = {item.id: item.kind for item in template}

    def counterpart(template_id: str) -> str | None:
        kind = kinds.get(template_id)
        if kind is None:
            return template_id  # a data store id; dropped later if it does not exist
        group = _kind_group(kind)
        match = next((service for service in services if service.kind in group), None)
        return match.id if match is not None else None

    for addition in added:
        addition.depends_on = [
            target
            for target in dict.fromkeys(counterpart(item) for item in addition.depends_on)
            if target is not None and target != addition.id
        ]
        for caller in template:
            if addition.id not in caller.depends_on or caller.kind == addition.kind:
                continue
            group = _kind_group(caller.kind)
            match = next(
                (service for service in services if service.kind in group and service not in added),
                None,
            )
            if match is not None and addition.id not in match.depends_on:
                match.depends_on.append(addition.id)


def _baseline_services(design: EnterpriseDesign) -> list[Service]:
    temporary = design.model_copy(deep=True)
    designer.baseline_component(temporary, "system")
    return temporary.services


def _baseline_stores(design: EnterpriseDesign) -> dict[str, DataStore]:
    temporary = design.model_copy(deep=True)
    temporary.requirements = design.requirements.model_copy(
        update={"archetypes": [*design.requirements.archetypes, "enterprise-rag"]}
    )
    designer.baseline_component(temporary, "data")
    return {store.id: store for store in temporary.data_stores}


def _scope_model_budget(design: EnterpriseDesign) -> None:
    """The limit, currency, and model-call scope come from the requirements.

    The shares are the API role's design choice and stay as proposed; only their amounts are
    recomputed against the limit.
    """
    policy = design.budget_policy
    if policy is None:
        return
    req = design.requirements
    policy.hard_limit = True
    policy.unavailable_behavior = "reject"
    policy.currency = req.currency
    policy.monthly_limit = req.monthly_budget
    policy.enforcement_scope = "model-calls"
    compute_allocations(policy)


def enforce_invariants(design: EnterpriseDesign) -> list[ValidationDiagnostic]:
    """Policy rules owned by Python, applied after every merge, edit, and baseline."""
    req = design.requirements
    diagnostics: list[ValidationDiagnostic] = []
    service_ids = {service.id for service in design.services}
    store_ids = {store.id for store in design.data_stores}
    for service in design.services:
        resolved = [item for item in service.depends_on if item in service_ids | store_ids]
        dropped = sorted(set(service.depends_on) - set(resolved))
        if dropped:
            diagnostics.append(
                _diag(
                    "REFERENCE_DROPPED",
                    f"{service.id}: removed unknown dependencies {', '.join(dropped)}",
                    "system",
                )
            )
        service.depends_on = [item for item in dict.fromkeys(resolved) if item != service.id]
        service.data_owned = [item for item in service.data_owned if item in store_ids]
    # The request path (gateway, application, admission, AI gateway) is not forced here.
    # Either call direction between admission and the AI gateway is valid, so a broken path is
    # reported by archai.application.checks and repaired by the role that owns the services.
    for store in design.data_stores:
        if store.owner_service and store.owner_service not in service_ids:
            store.owner_service = None
        if store.region not in req.data_residency and store.region != req.region:
            diagnostics.append(
                _diag(
                    "RESIDENCY_VIOLATION",
                    f"{store.id} region {store.region} is outside the allowed data residency",
                    "data",
                    "error",
                )
            )
    default_service = next(
        (s.id for s in design.services if s.kind in {"application", "orchestration"}), None
    )
    for contract in design.api_contracts:
        if contract.service_id and contract.service_id not in service_ids:
            contract.service_id = default_service
    if design.cache_policy:
        fields = list(design.cache_policy.namespace_fields)
        for name in REQUIRED_CACHE_NAMESPACE:
            if name not in fields:
                fields.append(name)
        design.cache_policy.namespace_fields = fields
        if req.data_classification == "restricted" and design.cache_policy.semantic_enabled:
            design.cache_policy.semantic_enabled = False
    if design.budget_policy:
        _scope_model_budget(design)
    if design.resilience:
        plan = design.resilience.dr_strategy or ""
        outside = regions_outside(plan, req.data_residency)
        if not plan.strip() or outside:
            design.resilience.dr_strategy = recovery_strategy(req)
            if outside:
                diagnostics.append(
                    _diag(
                        "DR_REGION_REJECTED",
                        f"The recovery plan named {', '.join(outside)}, outside data residency "
                        f"({', '.join(req.data_residency)}); ArchAI used its default plan",
                        "resilience",
                        "warning",
                    )
                )
        design.resilience.rto_minutes = req.rto_minutes
        design.resilience.rpo_minutes = req.rpo_minutes
    for endpoint in design.endpoints:
        if endpoint.quota_status != "planning":
            diagnostics.append(
                _diag(
                    "QUOTA_PLANNING",
                    f"{endpoint.id}: RPM, TPM, and context limit are a planning envelope until "
                    "the requirements include the account quota",
                    "routing",
                )
            )
        endpoint.quota_status = "planning"
    added_approvals = ensure_approval_operations(design)
    if added_approvals:
        diagnostics.append(
            _diag(
                "APPROVAL_INBOX",
                "Tool side effects require approval: the approvals inbox and decision "
                "operations were added",
                "api",
            )
        )
    if design.identity_policy:
        claims = list(design.identity_policy.required_claims)
        claims.extend(item for item in REQUIRED_CLAIMS if item not in claims)
        design.identity_policy.required_claims = claims
        design.identity_policy.object_level_authorization = True
        design.identity_policy.tenant_mode = req.tenant_isolation
        design.identity_policy.service_identities = [
            item
            for item in design.identity_policy.service_identities
            if item.service_id in service_ids
        ] or design.identity_policy.service_identities
    if design.observability:
        ids = list(design.observability.correlation_ids)
        ids.extend(item for item in REQUIRED_CORRELATION_IDS if item not in ids)
        design.observability.correlation_ids = ids
        design.observability.redaction_required = True
    attach_recovery_endpoints(design)
    for alias in design.model_aliases:
        if "embeddings" in alias.required_capabilities and alias.fallback_endpoint_ids:
            alias.fallback_endpoint_ids = []
            alias.endpoint_ids = alias.endpoint_ids[:1]
            diagnostics.append(
                _diag(
                    "EMBEDDING_FALLBACK_REMOVED",
                    f"{alias.id}: embeddings never fall back to a different vector space",
                    "routing",
                )
            )
    for code, message, component in derive_all(design):
        diagnostics.append(_diag(code, message, component))
    for code, message, component in align_fixed_facts(design):
        diagnostics.append(_diag(code, message, component))
    if (
        req.tool_side_effects == "approval"
        and uses_tools(req)
        and design.workflows
        and not any(workflow.hitl_required for workflow in design.workflows)
    ):
        for workflow in design.workflows:
            text = f"{workflow.name} {' '.join(workflow.steps)}".lower()
            if any(word in text for word in ("tool", "action", "approv", "execute")):
                workflow.hitl_required = True
        if not any(workflow.hitl_required for workflow in design.workflows):
            temporary = design.model_copy(deep=True)
            designer.baseline_component(temporary, "workflow")
            design.workflows.extend(w for w in temporary.workflows if w.hitl_required)
        diagnostics.append(
            _diag(
                "HITL_ENFORCED",
                "Tool side effects require approval: human approval gates were enforced",
                "workflow",
            )
        )
    return diagnostics
