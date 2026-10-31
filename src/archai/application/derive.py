"""Facts Python derives from the design instead of asking a second agent to restate them.

When two agents write the same fact in two places, every edit to one copy breaks the other.
Here the second copy follows from the first: a service's grants cover the calls in its
``depends_on`` and the stores it uses, the user sign-in flow can request every scope a role
holds, and the queue retry sentence states the queue policy's own numbers. These are additions
only; nothing a role wrote is removed.
"""

from __future__ import annotations

import re

from archai.schemas.models import EnterpriseDesign, ServiceIdentity

QUEUE_SENTENCE = re.compile(
    r"Queue jobs: at most \d+ deliveries, then the dead-letter queue(?: owned by [^.]+)?\.+\s*"
)


def mentions(text: str, identifier: str) -> bool:
    return bool(re.search(rf"(?<![\w-]){re.escape(identifier)}(?![\w-])", text))


def derive_service_grants(design: EnterpriseDesign) -> bool:
    """Every dependency in the call graph has a grant on the calling service's identity."""
    policy = design.identity_policy
    if policy is None or not design.services:
        return False
    stores = {store.id: store for store in design.data_stores}
    services = {service.id for service in design.services}
    identity_type = next(
        (item.identity_type for item in policy.service_identities), "workload identity"
    )
    identities = {item.service_id: item for item in policy.service_identities}
    changed = False
    for service in design.services:
        identity = identities.get(service.id)
        if identity is None:
            identity = ServiceIdentity(
                service_id=service.id, identity_type=identity_type, grants=[]
            )
            policy.service_identities.append(identity)
            identities[service.id] = identity
            changed = True
        needed: list[str] = []
        for target in service.depends_on:
            if target in services:
                needed.append(f"{target}: call its private API")
            elif target in stores:
                owner = stores[target].owner_service == service.id or target in service.data_owned
                needed.append(f"{target}: read/write" + (" (system of record)" if owner else ""))
        for target in service.data_owned:
            if target in stores and target not in service.depends_on:
                needed.append(f"{target}: read/write (system of record)")
        grants = list(identity.grants)
        for line, target in ((line, line.split(":", 1)[0]) for line in needed):
            if not any(mentions(grant, target) for grant in grants):
                grants.append(line)
        if grants != identity.grants:
            identity.grants = grants
            changed = True
    return changed


def derive_signin_scopes(design: EnterpriseDesign) -> bool:
    """The user sign-in flow can request every operation scope a role is granted."""
    policy = design.identity_policy
    if policy is None:
        return False
    operations = {scope for contract in design.api_contracts for scope in contract.scopes}
    held = [
        permission
        for role in policy.roles
        for permission in role.permissions
        if permission in operations
    ]
    changed = False
    for flow in policy.oauth_flows:
        if flow.grant_type != "authorization_code_pkce":
            continue
        scopes = list(flow.scopes)
        for scope in dict.fromkeys(held):
            if scope not in scopes:
                scopes.append(scope)
        if scopes != flow.scopes:
            flow.scopes = scopes
            changed = True
    return changed


def queue_sentence(design: EnterpriseDesign) -> str | None:
    """The delivery limit only; the dead-letter owner stays in queue_policy.dlq_owner."""
    queue = design.queue_policy
    if queue is None:
        return None
    return f"Queue jobs: at most {queue.max_attempts} deliveries, then the dead-letter queue."


def align_queue_retry(design: EnterpriseDesign) -> bool:
    """The retry policy opens with the queue policy's own delivery limit."""
    sentence = queue_sentence(design)
    if sentence is None or design.resilience is None:
        return False
    text = design.resilience.retry_policy or ""
    if text.startswith(sentence):
        return False
    rest = QUEUE_SENTENCE.sub("", text).strip()
    design.resilience.retry_policy = f"{sentence} {rest}".strip()
    return True


# Words models use for a guardrail owner, mapped to the service kind that runs that control.
_OWNER_WORDS = {
    "app": "application",
    "workflow": "application",
    "orchestrator": "application",
    "platform": "operations",
    "ops": "operations",
    "security": "operations",
    "audit": "operations",
    "observability": "operations",
    "edge": "gateway",
    "ingress": "gateway",
    "apim": "gateway",
    "rag": "retrieval",
    "search": "retrieval",
    "indexing": "ingestion",
    "tools": "tool-executor",
    "tool": "tool-executor",
    "budget": "policy",
    "admission": "policy",
    "llm-gateway": "ai-gateway",
    "model-gateway": "ai-gateway",
}


def derive_guard_owners(design: EnterpriseDesign) -> bool:
    """A guardrail owner written as a kind or a team word becomes the id of that service."""
    ids = {service.id for service in design.services}
    by_kind: dict[str, str] = {}
    for service in design.services:
        by_kind.setdefault(service.kind, service.id)
    by_kind.setdefault("orchestration", by_kind.get("application", ""))
    by_kind.setdefault("application", by_kind.get("orchestration", ""))
    changed = False
    for control in design.guardrails:
        owner = control.owner.strip()
        if owner in ids or any(mentions(owner, identifier) for identifier in ids):
            continue
        word = owner.lower().removeprefix("svc-")
        target = by_kind.get(word) or by_kind.get(_OWNER_WORDS.get(word, ""))
        if target:
            control.owner = target
            changed = True
    return changed


def derive_gateway_calls(design: EnterpriseDesign) -> bool:
    """The gateway depends on every service that owns an operation it publishes."""
    gateway = next((service for service in design.services if service.kind == "gateway"), None)
    if gateway is None:
        return False
    ids = {service.id for service in design.services}
    owners = [
        contract.service_id
        for contract in design.api_contracts
        if contract.service_id in ids and contract.service_id != gateway.id
    ]
    missing = [owner for owner in dict.fromkeys(owners) if owner not in gateway.depends_on]
    if missing:
        gateway.depends_on = [*gateway.depends_on, *(owner for owner in missing if owner)]
    return bool(missing)


def derive_all(design: EnterpriseDesign) -> list[tuple[str, str, str]]:
    notes: list[tuple[str, str, str]] = []
    if derive_gateway_calls(design):
        notes.append(
            (
                "GATEWAY_CALLS_DERIVED",
                "The gateway calls every service whose operation it publishes",
                "system",
            )
        )
    if derive_guard_owners(design):
        notes.append(("GUARD_OWNERS_DERIVED", "Guardrail owners name service ids", "guard"))
    if derive_service_grants(design):
        notes.append(
            (
                "GRANTS_DERIVED",
                "Service grants now cover every call and store in the design",
                "auth",
            )
        )
    if derive_signin_scopes(design):
        notes.append(
            ("SIGNIN_SCOPES_DERIVED", "User sign-in can request every scope a role holds", "auth")
        )
    if align_queue_retry(design):
        notes.append(
            (
                "QUEUE_RETRY_DERIVED",
                "The retry policy states the queue's own delivery limit",
                "resilience",
            )
        )
    return notes
