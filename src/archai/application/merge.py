"""Validate architect-model proposals and merge them into canonical state.

Model output is a proposal. This module normalizes IDs, drops dangling references, clamps numeric
values, and enforces policy invariants that pure Python code owns.
"""

from __future__ import annotations

import re
from decimal import Decimal
from functools import cache
from importlib.resources import files
from itertools import pairwise
from typing import Any

import yaml
from pydantic import BaseModel

from archai.application import designer
from archai.application.designer import (
    REQUIRED_CACHE_NAMESPACE,
    REQUIRED_CLAIMS,
    REQUIRED_CORRELATION_IDS,
    add_decision,
    compute_allocations,
    has_rag,
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


class ProposalMerger:
    """Merge one role proposal; ``aliases`` maps proposed IDs to normalized canonical IDs."""

    def __init__(self, design: EnterpriseDesign, source: str) -> None:
        self.design = design
        self.req = design.requirements
        self.source = source
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
        for component in ordered:
            if component not in components or component not in handlers:
                continue
            field, handler = handlers[component]
            value = getattr(proposal, field, None)
            if value is None:
                continue
            handler(value, proposal)
            state = self.design.components.get(component)
            if state is not None and state.status == ComponentStatus.valid:
                state.source = self.source
            merged.append(component)
        self.decisions(getattr(proposal, "decisions", []) or [], merged)
        return self.diagnostics

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
                    retention_days=int(_clamp(item.retention_days or 365, 1, 3650)),
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
        for kinds in REQUIRED_SERVICE_KINDS:
            if not any(service.kind in kinds for service in services):
                addition = next(service for service in baseline if service.kind == kinds[0])
                services.append(addition)
                self.diagnostics.append(
                    _diag(
                        "MERGE_ADDED_SERVICE",
                        f"Added required {kinds[0]} service '{addition.name}'",
                        "system",
                    )
                )
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
        size = int(_clamp(item.chunk_size_tokens or 800, 100, 8000))
        self.design.rag_pipeline = RAGPipeline(
            ingestion_steps=_clean(item.ingestion_steps, 12)
            or ["parse", "chunk", "embed", "index"],
            chunking_strategy=item.chunking_strategy or "structure-aware",
            chunk_size_tokens=size,
            chunk_overlap_tokens=int(_clamp(item.chunk_overlap_tokens or 0, 0, size // 2)),
            embedding_model_alias=embedding,
            embedding_dimensions=int(_clamp(item.embedding_dimensions or 1536, 64, 8192)),
            similarity_metric=item.similarity_metric or "cosine",
            retrieval_mode=item.retrieval_mode,
            top_k=int(_clamp(item.top_k or 8, 1, 50)),
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
            max_attempts=int(_clamp(item.max_attempts or 5, 1, 20)),
            max_age_seconds=int(_clamp(item.max_age_seconds or 3600, 60, 1_209_600)),
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
        chat = [e for e in self.design.endpoints if "embeddings" not in e.modalities]
        embedding = [e for e in self.design.endpoints if "embeddings" in e.modalities]

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
                    max_output_tokens=int(_clamp(alias.max_output_tokens or 1024, 64, 65_536)),
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
        auth = f"OIDC bearer token ({self.req.identity_provider or 'Entra ID'})"
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
                    auth=auth,
                    streaming=bool(item.streaming),
                    summary=item.summary or None,
                    service_id=service_id,
                    scopes=_clean(item.scopes, 6),
                    rate_limit_rpm=int(_clamp(item.rate_limit_rpm or 600, 1, 1_000_000)),
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
            allocations=allocations,
            soft_limit_percent=int(_clamp(item.soft_limit_percent or 80, 50, 100)),
            per_request_token_ceiling=int(
                _clamp(item.per_request_token_ceiling or 20_000, 256, 2_000_000)
            ),
            per_workflow_step_ceiling=int(_clamp(item.per_workflow_step_ceiling or 12, 1, 200)),
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
            ttl_seconds=int(_clamp(item.ttl_seconds or 300, 0, 86_400)),
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
        flows = [
            OAuthFlow(
                name=flow.name.strip() or flow.grant_type,
                grant_type=flow.grant_type,
                client=flow.client or "client",
                audience=flow.audience or f"api://{self.design.project}",
                scopes=_clean(flow.scopes, 10),
                pkce=flow.grant_type == "authorization_code_pkce",
                token_lifetime_minutes=int(_clamp(flow.token_lifetime_minutes or 60, 5, 1440)),
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
            idp=self.req.identity_provider or item.idp or baseline.idp,
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
            log_retention_days=int(_clamp(item.log_retention_days or 90, 1, 3650)),
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

    def decisions(self, items: list[Any], merged: list[str]) -> None:
        if not merged:
            return
        grouped: dict[str, list[Any]] = {}
        for item in items[:30]:
            component = item.component if item.component in merged else merged[0]
            grouped.setdefault(component, []).append(item)
        for component, decisions in grouped.items():
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

    def first(kinds: set[str]) -> Service | None:
        return next((service for service in design.services if service.kind in kinds), None)

    chain = (
        first({"gateway"}),
        first({"application", "orchestration"}),
        first({"policy"}),
        first({"ai-gateway"}),
    )
    for source, target in pairwise(chain):
        if source is not None and target is not None and target.id not in source.depends_on:
            source.depends_on.append(target.id)
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
        design.budget_policy.hard_limit = True
        design.budget_policy.unavailable_behavior = "reject"
        design.budget_policy.currency = req.currency
        if design.budget_policy.monthly_limit != req.monthly_budget:
            design.budget_policy.monthly_limit = req.monthly_budget
            compute_allocations(design.budget_policy)
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
