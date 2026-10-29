"""Request hops and trust boundaries compiled from canonical design state."""

from __future__ import annotations

from dataclasses import dataclass

from archai.schemas.models import (
    APIContract,
    EnterpriseDesign,
    Service,
    Workflow,
)

Participant = tuple[str, str, str]
Message = tuple[str, str, str, bool]


@dataclass(frozen=True)
class FlowStep:
    source: str
    target: str
    action: str
    dashed: bool = False
    owner: str = ""
    interface: str = "Internal call; no public route"
    payload: tuple[str, ...] = ()
    data: tuple[str, ...] = ()
    failure: str = "Fail closed for this hop; do not skip to a later step."


@dataclass(frozen=True)
class Hop:
    number: int
    source: str
    target: str
    action: str
    owner: str
    interface: str
    payload: tuple[str, ...]
    data: tuple[str, ...]
    failure: str


@dataclass(frozen=True)
class SequenceSpec:
    key: str
    title: str
    description: str
    participants: list[Participant]
    steps: list[FlowStep]


@dataclass(frozen=True)
class PathWalk:
    key: str
    title: str
    view_key: str | None
    hops: list[Hop]


def service_by_kind(design: EnterpriseDesign, *kinds: str) -> Service | None:
    return next((item for item in design.services if item.kind in kinds), None)


def primary_api(design: EnterpriseDesign) -> APIContract | None:
    contracts = list(design.api_contracts)
    if not contracts:
        return None
    if _interactive(design):
        streaming = [item for item in contracts if item.streaming]
        if streaming:
            return streaming[0]
        for path in ("/v1/chat", "/v1/jobs", "/v1/documents"):
            found = next(
                (item for item in contracts if item.path == path and item.method == "POST"),
                None,
            )
            if found:
                return found
    for path in ("/v1/jobs", "/v1/documents"):
        found = next(
            (item for item in contracts if item.path == path and item.method == "POST"), None
        )
        if found:
            return found
    posts = [item for item in contracts if item.method == "POST"]
    return posts[0] if posts else contracts[0]


def request_flow(design: EnterpriseDesign) -> tuple[list[Participant], list[Message]]:
    spec = request_sequence(design)
    return spec.participants, _messages(spec.steps)


def request_hops(design: EnterpriseDesign) -> list[Hop]:
    spec = request_sequence(design)
    return _hops(spec.participants, spec.steps)


def request_sequence(design: EnterpriseDesign) -> SequenceSpec:
    gateway = service_by_kind(design, "gateway")
    app = service_by_kind(design, "application", "orchestration")
    retrieval = service_by_kind(design, "retrieval")
    admission = service_by_kind(design, "policy")
    ai = service_by_kind(design, "ai-gateway")
    api = primary_api(design)
    policy = design.identity_policy
    participants: dict[str, Participant] = {}
    steps: list[FlowStep] = []

    def add(pid: str, label: str, style: str) -> None:
        participants[pid] = (pid, label, style)

    add("client", "Client", "client")
    if policy:
        add("idp", policy.idp, "identity")
        claims = tuple(policy.required_claims) or ("iss", "aud", "exp")
        grants = {flow.grant_type for flow in policy.oauth_flows}
        if "authorization_code_pkce" in grants:
            steps += [
                _step(
                    "client",
                    "idp",
                    f"Sign in with {policy.idp} (authorization code + PKCE)",
                    owner=policy.idp,
                    interface=f"{policy.idp} /authorize",
                    payload=claims,
                    failure=(
                        f"{policy.idp} unavailable or MFA denied; the client never calls the API."
                    ),
                ),
                _step(
                    "idp",
                    "client",
                    "Access token",
                    dashed=True,
                    owner=policy.idp,
                    interface=f"{policy.idp} /token",
                    payload=claims,
                    failure="Token request rejected; retry sign-in.",
                ),
            ]
        elif "client_credentials" in grants:
            steps.append(
                _step(
                    "client",
                    "idp",
                    f"Client credentials against {policy.idp}",
                    owner=policy.idp,
                    interface=f"{policy.idp} /token",
                    payload=claims,
                    failure=f"{policy.idp} rejected the client assertion; do not call the API.",
                )
            )
    if gateway:
        add("gw", gateway.name, "gateway")
    if app:
        add("app", app.name, "application")
    dest = "gw" if gateway else "app"
    owner_dest = _owner(gateway if gateway else app, dest)
    if api:
        steps.append(
            _step(
                "client",
                dest,
                f"{api.method} {api.path} with {api.auth}",
                owner=owner_dest,
                interface=_api_interface(api),
                payload=tuple(api.request_fields),
                failure=(
                    f"401 if {api.auth} fails"
                    + (f"; 429 if over {api.rate_limit_rpm} rpm" if api.rate_limit_rpm else "")
                    + ". Downstream is not reached."
                ),
            )
        )
        if gateway and app:
            claims = tuple(policy.required_claims) if policy else ()
            steps.append(
                _step(
                    "gw",
                    "gw",
                    f"Validate {api.auth}, rate limit, correlation ID",
                    owner=_owner(gateway, "gw"),
                    interface="Gateway inbound policy",
                    payload=claims,
                    failure="Reject at the gateway. Do not forward a request with failed claims.",
                )
            )
            steps.append(
                _step(
                    "gw",
                    "app",
                    "Authorized request + trusted claims",
                    owner=_owner(app, "app"),
                    interface="Gateway → application",
                    payload=claims,
                    failure="Do not forward if claim-to-tenant mapping fails.",
                )
            )
    if retrieval and design.rag_pipeline and app:
        add("ret", retrieval.name, "application")
        rag = design.rag_pipeline
        stores = tuple(store.name for store in design.data_stores)
        steps += [
            _step(
                "app",
                "ret",
                f"Retrieve ({rag.retrieval_mode}, top-{rag.top_k})",
                owner=_owner(retrieval, "ret"),
                interface=f"{retrieval.name} retrieval",
                payload=("query", "tenant", "acl", rag.acl_enforcement),
                data=stores,
                failure=(
                    f"Empty ACL-trimmed result or store timeout; {rag.acl_enforcement}; "
                    f"{rag.grounding_policy}."
                ),
            ),
            _step(
                "ret",
                "app",
                "Permitted passages + citations",
                dashed=True,
                owner=_owner(app, "app"),
                interface=f"{retrieval.name} retrieval",
                payload=("passages", "citations", "index_version"),
                data=stores,
                failure="Do not answer from documents the caller is not allowed to see.",
            ),
        ]
    if design.budget_policy and admission and app:
        add("adm", admission.name, "policy")
        budget = design.budget_policy
        ledger = tuple(
            store.name
            for store in design.data_stores
            if "ledger" in store.purpose.lower() or "budget" in store.name.lower()
        )
        steps.append(
            _step(
                "app",
                "adm",
                f"Reserve against {budget.monthly_limit} {budget.currency} hard limit",
                owner=_owner(admission, "adm"),
                interface="POST /internal/budget/reservations",
                payload=("alias", "token_bound", "principal", "reservation_id"),
                data=ledger,
                failure=(
                    f"409 if over {budget.monthly_limit} {budget.currency}; "
                    f"{budget.unavailable_behavior} when the ledger is unavailable."
                ),
            )
        )
    chat = [item for item in design.endpoints if "embeddings" not in item.modalities]
    dispatcher = "adm" if "adm" in participants else "app"
    if ai and chat and dispatcher in participants:
        add("ai", ai.name, "ai")
        add("llm", f"{chat[0].provider} endpoint", "model")
        attempts = design.routing_policy.max_attempts if design.routing_policy else 2
        steps += [
            _step(
                dispatcher,
                "ai",
                "Dispatch with attempt IDs",
                owner=_owner(ai, "ai"),
                interface=ai.name,
                payload=("reservation_id", "attempt_id", "alias"),
                failure="Do not call a provider without an attempt record.",
            ),
            _step(
                "ai",
                "llm",
                f"Managed API call to {chat[0].provider} (`{chat[0].id}`)",
                owner=f"{chat[0].provider} (`{chat[0].id}`)",
                interface=f"{chat[0].provider} {chat[0].deployment_id}",
                payload=("prompt", "max_tokens"),
                failure=(f"429 or timeout. {ai.name} is the retry owner; max {attempts} attempts."),
            ),
            _step(
                "llm",
                "ai",
                "Streamed tokens + usage",
                dashed=True,
                owner=_owner(ai, "ai"),
                interface=f"{chat[0].provider} {chat[0].deployment_id}",
                payload=("tokens", "usage"),
                failure="If usage is missing, keep the reservation unresolved.",
            ),
            _step(
                "ai",
                "app" if app else dispatcher,
                "Stream + usage",
                dashed=True,
                owner=_owner(app, "app"),
                interface=ai.name,
                payload=("tokens", "usage"),
                failure="Application still settles even if the client has gone.",
            ),
        ]
    if design.guardrails and app:
        output = next(
            (item for item in design.guardrails if item.stage == "output"), design.guardrails[0]
        )
        steps.append(
            _step(
                "app",
                "app",
                f"Validate output: {output.control}",
                owner=output.owner,
                interface=output.enforcement,
                payload=(output.stage, output.control),
                failure="Failed output check; do not send the completion to the client.",
            )
        )
    if design.budget_policy and admission and "adm" in participants and app:
        ledger = tuple(
            store.name
            for store in design.data_stores
            if "ledger" in store.purpose.lower() or "budget" in store.name.lower()
        )
        steps.append(
            _step(
                "app",
                "adm",
                "Settle actual usage",
                owner=_owner(admission, "adm"),
                interface="POST /internal/budget/reservations/{id}/settle",
                payload=("reservation_id", "input_tokens", "output_tokens"),
                data=ledger,
                failure="Unknown usage stays as liability; do not release the reservation.",
            )
        )
    if api and app:
        response = "SSE stream" if api.streaming else "JSON response"
        steps.append(
            _step(
                "app",
                "client",
                f"{response} for {api.method} {api.path}",
                dashed=True,
                owner=_owner(app, "app"),
                interface=_api_interface(api),
                payload=tuple(api.response_fields),
                failure="Client disconnect; settlement still runs if a reservation exists.",
            )
        )
    ordered = [participants[pid] for pid in participants]
    return SequenceSpec(
        "request",
        "Interactive request flow",
        "Compiled from the primary API contract, identity, retrieval, budget, and routes.",
        ordered,
        steps,
    )


def other_paths(design: EnterpriseDesign) -> list[PathWalk]:
    walks: list[PathWalk] = []
    for spec in identity_sequences(design):
        walks.append(PathWalk(spec.key, spec.title, spec.key, _hops(spec.participants, spec.steps)))
    if design.rag_pipeline:
        walks.append(_ingestion_path(design))
    for workflow in design.workflows:
        walks.append(_workflow_path(design, workflow))
    fallback = fallback_sequence(design)
    if fallback:
        walks.append(
            PathWalk(
                fallback.key,
                fallback.title,
                fallback.key,
                _hops(fallback.participants, fallback.steps),
            )
        )
    async_spec = async_sequence(design)
    if async_spec:
        walks.append(
            PathWalk(
                async_spec.key,
                async_spec.title,
                async_spec.key,
                _hops(async_spec.participants, async_spec.steps),
            )
        )
    if design.guardrails:
        walks.append(_guardrail_path(design))
    return walks


def identity_sequences(design: EnterpriseDesign) -> list[SequenceSpec]:
    policy = design.identity_policy
    if policy is None:
        return []
    idp = policy.idp
    gateway = service_by_kind(design, "gateway")
    app = service_by_kind(design, "application", "orchestration")
    claims = tuple(policy.required_claims) or ("iss", "aud", "exp")
    grants = {flow.grant_type for flow in policy.oauth_flows}
    specs: list[SequenceSpec] = []
    if "authorization_code_pkce" in grants:
        parts = [
            ("user", "User", "client"),
            ("client", "Client app", "client"),
            ("idp", idp, "identity"),
            ("gw", gateway.name if gateway else "API gateway", "gateway"),
            ("app", app.name if app else "Application", "application"),
        ]
        api = primary_api(design)
        call = (
            f"{api.method} {api.path} with bearer access token"
            if api
            else "API call with bearer access token"
        )
        specs.append(
            SequenceSpec(
                "oauth-user",
                "User sign-in: OAuth 2.0 authorization code + PKCE",
                f"Public clients obtain short-lived tokens from {idp}; the gateway validates them.",
                parts,
                [
                    _step("user", "client", "Open application", owner="Client application"),
                    _step(
                        "client",
                        "client",
                        "Create code_verifier + code_challenge",
                        owner="Client application",
                        interface="PKCE",
                    ),
                    _step(
                        "client",
                        "idp",
                        "/authorize (client_id, scope, code_challenge)",
                        owner=idp,
                        interface=f"{idp} /authorize",
                        payload=tuple(
                            scope
                            for flow in policy.oauth_flows
                            if flow.grant_type == "authorization_code_pkce"
                            for scope in flow.scopes
                        ),
                        failure=f"{idp} denies authorize; the API is not called.",
                    ),
                    _step(
                        "idp",
                        "user",
                        "Authenticate + MFA + consent",
                        owner=idp,
                        interface=f"{idp} login",
                        failure="MFA or consent denied.",
                    ),
                    _step(
                        "idp",
                        "client",
                        "Authorization code (redirect)",
                        dashed=True,
                        owner=idp,
                        interface=f"{idp} redirect",
                    ),
                    _step(
                        "client",
                        "idp",
                        "/token (code + code_verifier)",
                        owner=idp,
                        interface=f"{idp} /token",
                        failure="Invalid verifier; retry sign-in.",
                    ),
                    _step(
                        "idp",
                        "client",
                        "Access + refresh token",
                        dashed=True,
                        owner=idp,
                        interface=f"{idp} /token",
                        payload=claims,
                    ),
                    _step(
                        "client",
                        "gw",
                        call,
                        owner=_owner(gateway, "gw"),
                        interface=_api_interface(api) if api else "Gateway",
                        payload=claims,
                        failure="401 if the access token is missing or wrong audience.",
                    ),
                    _step(
                        "gw",
                        "gw",
                        "Validate " + ", ".join(claims),
                        owner=_owner(gateway, "gw"),
                        interface="Gateway inbound policy",
                        payload=claims,
                        failure="Reject at the gateway.",
                    ),
                    _step(
                        "gw",
                        "app",
                        "Forward with validated claims",
                        owner=_owner(app, "app"),
                        interface="Gateway → application",
                        payload=claims,
                    ),
                    _step(
                        "app",
                        "app",
                        policy.tenant_mapping or "Map claims to tenant, department, ACL",
                        owner=_owner(app, "app"),
                        interface="Object-level authorization"
                        if policy.object_level_authorization
                        else "Application identity mapping",
                        failure="Do not serve another tenant's objects.",
                    ),
                ],
            )
        )
    if "client_credentials" in grants:
        worker = service_by_kind(design, "worker", "ingestion")
        admission = service_by_kind(design, "policy")
        specs.append(
            SequenceSpec(
                "oauth-service",
                "Service-to-service: workload identity + client credentials",
                f"Services exchange a federated workload token at {idp}.",
                [
                    ("svc", worker.name if worker else "Internal service", "worker"),
                    ("wi", "Workload identity", "identity"),
                    ("idp", idp, "identity"),
                    ("api", admission.name if admission else "Internal API", "policy"),
                ],
                [
                    _step(
                        "svc",
                        "wi",
                        "Request federated token (pod/app identity)",
                        owner="Workload identity",
                        interface="Platform workload identity",
                    ),
                    _step(
                        "wi",
                        "svc",
                        "Signed workload assertion",
                        dashed=True,
                        owner="Workload identity",
                    ),
                    _step(
                        "svc",
                        "idp",
                        "client_credentials with client_assertion",
                        owner=idp,
                        interface=f"{idp} /token",
                        failure=f"{idp} rejected the assertion.",
                    ),
                    _step(
                        "idp",
                        "svc",
                        "Access token (aud = internal API)",
                        dashed=True,
                        owner=idp,
                        payload=claims,
                    ),
                    _step(
                        "svc",
                        "api",
                        "Call with bearer token",
                        owner=_owner(admission, "api"),
                        failure="401 wrong audience or caller.",
                    ),
                    _step(
                        "api",
                        "api",
                        "Validate audience, roles, and caller identity",
                        owner=_owner(admission, "api"),
                        payload=claims,
                    ),
                ],
            )
        )
    if "on_behalf_of" in grants:
        tools = service_by_kind(design, "tool-executor")
        specs.append(
            SequenceSpec(
                "oauth-obo",
                "Delegated tool access: on-behalf-of",
                "Tool calls act with the user's delegated permissions only.",
                [
                    ("app", app.name if app else "Application", "application"),
                    ("tools", tools.name if tools else "Tool service", "application"),
                    ("idp", idp, "identity"),
                    ("biz", "Business API", "data"),
                ],
                [
                    _step(
                        "app",
                        "tools",
                        "Tool request with user token",
                        owner=_owner(tools, "tools"),
                    ),
                    _step(
                        "tools",
                        "idp",
                        "OBO exchange for downstream scope",
                        owner=idp,
                        interface=f"{idp} on-behalf-of",
                        failure="OBO denied; do not call the business API as the app.",
                    ),
                    _step(
                        "idp",
                        "tools",
                        "Delegated token (short-lived)",
                        dashed=True,
                        owner=idp,
                    ),
                    _step(
                        "tools",
                        "biz",
                        "Call with delegated token",
                        owner="Business API",
                    ),
                    _step(
                        "biz",
                        "tools",
                        "Result (user-authorized data only)",
                        dashed=True,
                        owner="Business API",
                    ),
                ],
            )
        )
    return specs


def fallback_sequence(design: EnterpriseDesign) -> SequenceSpec | None:
    aliases = [alias for alias in design.model_aliases if alias.fallback_endpoint_ids]
    if not aliases:
        return None
    alias = aliases[0]
    endpoints = {endpoint.id: endpoint for endpoint in design.endpoints}
    primary = endpoints[alias.endpoint_ids[0]]
    fallback = endpoints[alias.fallback_endpoint_ids[0]]
    attempts = design.routing_policy.max_attempts if design.routing_policy else 2
    admission = service_by_kind(design, "policy")
    ai = service_by_kind(design, "ai-gateway")
    return SequenceSpec(
        "fallback",
        f"Provider fallback for {alias.id}",
        "Fallback happens only before streaming starts, inside the deadline and budget.",
        [
            ("adm", admission.name if admission else "Model admission", "policy"),
            ("ai", ai.name if ai else "AI gateway", "ai"),
            ("p1", f"{primary.provider} (primary)", "model"),
            ("p2", f"{fallback.provider} (fallback)", "model"),
        ],
        [
            _step(
                "adm",
                "ai",
                "Dispatch attempt 1 (reservation A)",
                owner=_owner(ai, "ai"),
                payload=("reservation_id", "attempt_id", alias.id),
            ),
            _step(
                "ai",
                "p1",
                f"Call {primary.provider} (`{primary.id}`)",
                owner=f"{primary.provider} (`{primary.id}`)",
                interface=f"{primary.provider} {primary.deployment_id}",
            ),
            _step(
                "p1",
                "ai",
                "Timeout / 429 / 5xx before first byte",
                dashed=True,
                owner=_owner(ai, "ai"),
                failure="No fallback after the first streamed byte.",
            ),
            _step(
                "ai",
                "ai",
                "Circuit check + eligibility re-check",
                owner=_owner(ai, "ai"),
            ),
            _step(
                "ai",
                "adm",
                "Request reservation B for attempt 2",
                owner=_owner(admission, "adm"),
                interface="POST /internal/budget/reservations",
                failure="409 if attempt 2 would exceed the hard limit.",
            ),
            _step(
                "adm",
                "ai",
                "Reservation B granted",
                dashed=True,
                owner=_owner(admission, "adm"),
            ),
            _step(
                "ai",
                "p2",
                f"Call {fallback.provider} (`{fallback.id}`)",
                owner=f"{fallback.provider} (`{fallback.id}`)",
                interface=f"{fallback.provider} {fallback.deployment_id}",
                failure=f"Stop after {attempts} attempts.",
            ),
            _step(
                "p2",
                "ai",
                "Streamed response + usage",
                dashed=True,
                owner=_owner(ai, "ai"),
            ),
            _step(
                "ai",
                "adm",
                "Settle B; A stays unresolved until reconciled",
                owner=_owner(admission, "adm"),
                interface="POST /internal/budget/reservations/{id}/settle",
            ),
        ],
    )


def async_sequence(design: EnterpriseDesign) -> SequenceSpec | None:
    if design.queue_policy is None:
        return None
    worker = service_by_kind(design, "worker", "ingestion")
    app = service_by_kind(design, "application", "orchestration")
    jobs = next((item for item in design.api_contracts if item.path == "/v1/jobs"), None)
    call = f"{jobs.method} {jobs.path}" if jobs else "POST /v1/jobs"
    broker = design.queue_policy.broker
    return SequenceSpec(
        "async",
        "Asynchronous job processing",
        f"{broker}: at-least-once delivery, idempotent handlers, and DLQ.",
        [
            ("client", "Client", "client"),
            ("app", app.name if app else "Application", "application"),
            ("db", "State store (outbox)", "data"),
            ("q", broker, "queue"),
            ("w", worker.name if worker else "Worker", "worker"),
        ],
        [
            _step(
                "client",
                "app",
                f"{call} (idempotency key)",
                owner=_owner(app, "app"),
                interface=_api_interface(jobs) if jobs else call,
                payload=tuple(jobs.request_fields) if jobs else ("job_type", "idempotency_key"),
                failure="Reject duplicate idempotency keys; do not enqueue twice.",
            ),
            _step(
                "app",
                "db",
                "Insert job + outbox row in one transaction",
                owner=_owner(app, "app"),
                data=tuple(store.name for store in design.data_stores),
            ),
            _step(
                "app",
                "client",
                "202 Accepted + status URL",
                dashed=True,
                owner=_owner(app, "app"),
                payload=tuple(jobs.response_fields) if jobs else ("job_id", "status_url"),
            ),
            _step("db", "q", "Outbox relay publishes reference message", owner=broker),
            _step(
                "q",
                "w",
                "Deliver (lock / visibility timeout)",
                owner=_owner(worker, "w"),
                interface=broker,
            ),
            _step(
                "w",
                "w",
                "Dedupe, process within quota",
                owner=_owner(worker, "w"),
            ),
            _step(
                "w",
                "db",
                "Idempotent status transition",
                owner=_owner(worker, "w"),
            ),
            _step(
                "w",
                "q",
                f"Complete, or dead-letter after {design.queue_policy.max_attempts} tries",
                dashed=True,
                owner=design.queue_policy.dlq_owner,
                failure=f"After {design.queue_policy.max_attempts} tries, {design.queue_policy.dlq_owner} owns the DLQ.",
            ),
        ],
    )


def trust_boundaries(design: EnterpriseDesign) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    gateway = service_by_kind(design, "gateway")
    admission = service_by_kind(design, "policy")
    ai = service_by_kind(design, "ai-gateway")
    app = service_by_kind(design, "application", "orchestration")
    if design.identity_policy:
        rows.append(
            (
                "Authentication and request limits",
                gateway.name if gateway else "Enterprise API gateway",
                "edge",
            )
        )
    if design.budget_policy:
        owner = admission.name if admission else "Application model-admission service"
        rows.append(("Token limits and budget reservation", owner, "application"))
        rows.append(("Usage settlement", owner, "application"))
    if ai or design.routing_policy:
        rows.append(
            (
                "Provider retry and timeout",
                ai.name if ai else "AI gateway",
                "inside, toward providers",
            )
        )
    if design.cache_policy:
        rows.append(("Cache authorization", app.name if app else "Application", "application"))
    if design.observability:
        rows.append(("Telemetry", "OpenTelemetry pipeline", "operations"))
    return rows


def control_ownership(design: EnterpriseDesign) -> dict[str, str]:
    mapping = {
        "Authentication and request limits": "authentication",
        "Token limits and budget reservation": "budget_reservation",
        "Usage settlement": "usage_settlement",
        "Provider retry and timeout": "provider_retry",
        "Cache authorization": "cache_authorization",
        "Telemetry": "logging",
    }
    slugs = {
        "authentication": "enterprise-api-gateway",
        "request_limits": "enterprise-api-gateway",
        "token_limits": "application-model-admission",
        "budget_reservation": "application-model-admission",
        "provider_retry": "ai-gateway",
        "timeout": "ai-gateway",
        "circuit_breaker": "ai-gateway",
        "cache_authorization": "application",
        "usage_settlement": "application-model-admission",
        "logging": "opentelemetry-pipeline",
    }
    present = {
        mapping[label] for label, _owner, _bound in trust_boundaries(design) if label in mapping
    }
    if "authentication" in present:
        present.add("request_limits")
    if "provider_retry" in present:
        present.update({"timeout", "circuit_breaker"})
    if "budget_reservation" in present:
        present.add("token_limits")
    return {key: value for key, value in slugs.items() if key in present}


def _interactive(design: EnterpriseDesign) -> bool:
    req = design.requirements
    if req.users == ["scheduler"]:
        return False
    text = " ".join(req.archetypes).lower()
    if any(word in text for word in ("rag", "agent", "chat", "copilot", "assistant")):
        return True
    return bool(req.users) and "classification" not in text


def _step(
    source: str,
    target: str,
    action: str,
    *,
    dashed: bool = False,
    owner: str = "",
    interface: str = "Internal call; no public route",
    payload: tuple[str, ...] = (),
    data: tuple[str, ...] = (),
    failure: str = "Fail closed for this hop; do not skip to a later step.",
) -> FlowStep:
    return FlowStep(source, target, action, dashed, owner, interface, payload, data, failure)


def _messages(steps: list[FlowStep]) -> list[Message]:
    return [(item.source, item.target, item.action, item.dashed) for item in steps]


def _hops(participants: list[Participant], steps: list[FlowStep]) -> list[Hop]:
    labels = {pid: label for pid, label, _style in participants}
    return [
        Hop(
            index,
            labels.get(item.source, item.source),
            labels.get(item.target, item.target),
            item.action,
            item.owner or labels.get(item.target, item.target),
            item.interface,
            item.payload,
            item.data,
            item.failure,
        )
        for index, item in enumerate(steps, start=1)
    ]


def _owner(service: Service | None, fallback: str) -> str:
    if service:
        return f"{service.name} (`{service.id}`)"
    return fallback


def _api_interface(api: APIContract | None) -> str:
    if api is None:
        return "Internal call; no public route"
    extra = ", streaming" if api.streaming else ""
    return f"`{api.method} {api.path}`{extra}"


def _ingestion_path(design: EnterpriseDesign) -> PathWalk:
    pipeline = design.rag_pipeline
    assert pipeline is not None
    worker = service_by_kind(design, "ingestion", "worker")
    docs = next((item for item in design.api_contracts if item.path == "/v1/documents"), None)
    stores = tuple(store.name for store in design.data_stores)
    queue = design.queue_policy
    hops: list[Hop] = []
    previous = "Application"
    for index, text in enumerate(pipeline.ingestion_steps, start=1):
        owner = _owner(worker, "Ingestion")
        interface = (
            _api_interface(docs)
            if index == 1 and docs
            else (queue.broker if queue else "ingestion pipeline")
        )
        hops.append(
            Hop(
                index,
                previous,
                worker.name if worker else "Ingestion",
                text,
                owner,
                interface,
                tuple(docs.request_fields) if index == 1 and docs else (),
                stores,
                (
                    f"Dead-letter after {queue.max_attempts} tries; {queue.dlq_owner} owns the DLQ."
                    if queue
                    else "Fail the job; do not index a partial document."
                ),
            )
        )
        previous = worker.name if worker else "Ingestion"
    return PathWalk("ingestion", "Document ingestion pipeline", "ingestion", hops)


def _workflow_path(design: EnterpriseDesign, workflow: Workflow) -> PathWalk:
    app = service_by_kind(design, "application", "orchestration")
    tools = service_by_kind(design, "tool-executor")
    approval = next((item for item in design.api_contracts if "approvals" in item.path), None)
    hops: list[Hop] = []
    previous = "Client"
    for index, text in enumerate(workflow.steps, start=1):
        lower = text.lower()
        if workflow.hitl_required and approval and ("approv" in lower or "human" in lower):
            owner = _owner(app, "Application")
            interface = _api_interface(approval)
            payload = tuple(approval.request_fields)
            failure = "Do not execute a tool whose arguments were not approved."
            target = app.name if app else "Application"
        elif "tool" in lower and tools:
            owner = _owner(tools, "Tools")
            interface = tools.name
            payload = ()
            failure = "Tool side effects follow the approval binding."
            target = tools.name
        else:
            owner = _owner(app, "Application")
            interface = _api_interface(primary_api(design))
            payload = ()
            failure = "Fail closed; do not skip a workflow step."
            target = app.name if app else "Application"
        hops.append(Hop(index, previous, target, text, owner, interface, payload, (), failure))
        previous = target
    return PathWalk(
        f"workflow-{workflow.id.removeprefix('workflow-')}",
        workflow.name,
        f"workflow-{workflow.id.removeprefix('workflow-')}",
        hops,
    )


def _guardrail_path(design: EnterpriseDesign) -> PathWalk:
    hops = [
        Hop(
            index,
            control.stage,
            control.owner,
            control.control,
            control.owner,
            control.enforcement,
            (control.stage,),
            (),
            f"{control.enforcement}: fail closed at the {control.stage} stage.",
        )
        for index, control in enumerate(design.guardrails, start=1)
    ]
    return PathWalk("guardrails", "Guardrail stages", "guardrails", hops)
