"""Structural checks Python reports instead of silently fixing.

A silent fix can undo a role's correct choice and leave the verifier arguing with a value no
role can change. These checks describe the defect as a finding with a stable id, and the
repair loop sends it to the role that owns the named fields, like a verifier finding.
"""

from __future__ import annotations

import re
from typing import Literal

from archai.application.derive import QUEUE_SENTENCE, mentions
from archai.schemas.models import EnterpriseDesign, Service, VerificationFinding

CHECK_PREFIX = "[ArchAI check] "
_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "ten": 10}
_DELIVERY_COUNT = re.compile(
    r"\b(\d+|one|two|three|four|five|six|seven|ten)\s+(?:[a-z-]+\s+){0,2}"
    r"(?:deliveries|delivery attempts|receives|redeliveries)\b",
    re.IGNORECASE,
)
_PATH = re.compile(
    r"(?:\b(?:GET|POST|PUT|PATCH|DELETE)\s+)?(/v\d+/[A-Za-z0-9_{}/.-]*[A-Za-z0-9_}])"
)
_ID = re.compile(r"\b((?:api|svc|store)-[a-z0-9][a-z0-9-]*[a-z0-9])\b")


def _first(design: EnterpriseDesign, kinds: set[str]) -> Service | None:
    return next((service for service in design.services if service.kind in kinds), None)


def _reaches(services: dict[str, Service], start: str, goal: str) -> bool:
    seen: set[str] = set()
    stack = [start]
    while stack:
        current = stack.pop()
        if current == goal:
            return True
        if current in seen or current not in services:
            continue
        seen.add(current)
        stack.extend(item for item in services[current].depends_on if item in services)
    return False


def _cycle(services: dict[str, Service]) -> list[str] | None:
    """One dependency cycle among services, as the ids along it, or None."""
    state: dict[str, int] = {}
    path: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        path.append(node)
        for nxt in services[node].depends_on:
            if nxt not in services:
                continue
            if state.get(nxt) == 1:
                return [*path[path.index(nxt) :], nxt]
            if nxt not in state:
                found = visit(nxt)
                if found:
                    return found
        path.pop()
        state[node] = 2
        return None

    for node in services:
        if node not in state:
            found = visit(node)
            if found:
                return found
    return None


def _finding(
    code: str,
    issue: str,
    recommendation: str,
    fields: list[str],
    components: list[str] | None = None,
    severity: Literal["blocking", "warning"] = "blocking",
) -> VerificationFinding:
    owners = components or ["system"]
    return VerificationFinding(
        severity=severity,
        component=owners[0],
        issue=CHECK_PREFIX + issue,
        recommendation=recommendation,
        id=f"P-{code}",
        fields=fields,
        components=owners,
    )


def _template(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", path.split("?", 1)[0].rstrip("/"))


def _known(identifier: str, ids: set[str]) -> bool:
    """Exact id, or a shortened or lengthened form of exactly one id (models truncate slugs)."""
    if identifier in ids:
        return True
    return any(name.startswith(identifier) or identifier.startswith(name) for name in ids)


def retry_count_findings(design: EnterpriseDesign) -> list[VerificationFinding]:
    queue, resilience = design.queue_policy, design.resilience
    if queue is None or resilience is None:
        return []
    text = QUEUE_SENTENCE.sub("", resilience.retry_policy or "")
    stated: set[int] = set()
    for match in _DELIVERY_COUNT.finditer(text):
        word = match.group(1).lower()
        stated.add(int(word) if word.isdigit() else _NUMBERS[word])
    wrong = sorted(number for number in stated if number and number != queue.max_attempts)
    if not wrong:
        return []
    return [
        _finding(
            "RETRY_COUNT",
            f"resilience.retry_policy states {', '.join(map(str, wrong))} queue deliveries, but "
            f"queue_policy.max_attempts is {queue.max_attempts}. Workers cannot implement both.",
            "State queue delivery limits only through queue_policy.max_attempts; remove the "
            "other count from retry_policy.",
            ["resilience.retry_policy", "queue_policy.max_attempts"],
            ["resilience"],
        )
    ]


def workflow_reference_findings(design: EnterpriseDesign) -> list[VerificationFinding]:
    """Workflow steps that name an operation, service, or store the design does not define."""
    paths = {_template(contract.path) for contract in design.api_contracts}
    ids = (
        {contract.id for contract in design.api_contracts}
        | {service.id for service in design.services}
        | {store.id for store in design.data_stores}
    )
    findings: list[VerificationFinding] = []
    for workflow in design.workflows:
        text = " ".join(workflow.steps)
        missing_paths = sorted(
            {match for match in _PATH.findall(text) if _template(match) not in paths}
        )
        missing_ids = sorted({match for match in _ID.findall(text) if not _known(match, ids)})
        if not missing_paths and not missing_ids:
            continue
        named = ", ".join([*missing_paths, *missing_ids])
        findings.append(
            _finding(
                f"WORKFLOW_REFERENCE-{workflow.id}",
                f"{workflow.id} names {named}, which no API contract, service, or store in the "
                "design defines. Engineering cannot build that step as written.",
                "Point the step at an existing operation, service, or store, or add the missing "
                "contract or service.",
                [f"workflows.{workflow.id}.steps", "api_contracts"],
                ["workflow", "api"] if missing_paths else ["workflow", "system"],
            )
        )
    return findings


def guard_owner_findings(design: EnterpriseDesign) -> list[VerificationFinding]:
    ids = {service.id for service in design.services}
    unknown = [
        control
        for control in design.guardrails
        if not any(mentions(control.owner, identifier) for identifier in ids)
    ]
    if not unknown or not ids:
        return []
    names = ", ".join(f"{control.id} ({control.owner})" for control in unknown[:6])
    return [
        _finding(
            "GUARD_OWNER",
            f"Guardrails {names} are owned by something that is not a service in the design, so "
            "no team runs them.",
            "Set each guardrail owner to the id of the service that enforces it.",
            [f"guardrails.{control.id}.owner" for control in unknown[:6]],
            ["guard"],
            severity="warning",  # a label, not unsafe behaviour
        )
    ]


def design_checks(design: EnterpriseDesign) -> list[VerificationFinding]:
    """Blocking structural defects in the service graph."""
    services = {service.id: service for service in design.services}
    if not services:
        return []
    findings: list[VerificationFinding] = []
    gateway = _first(design, {"gateway"})
    app = _first(design, {"application", "orchestration"})
    admission = _first(design, {"policy"})
    ai_gateway = _first(design, {"ai-gateway"})
    if (
        gateway
        and app
        and ai_gateway
        and not (
            _reaches(services, gateway.id, app.id) and _reaches(services, app.id, ai_gateway.id)
        )
    ):
        findings.append(
            _finding(
                "REQUEST_PATH",
                f"No dependency path runs {gateway.id} → {app.id} → {ai_gateway.id}, so a user "
                "request cannot reach a model through the enterprise gateway and the "
                "application service.",
                "Add the missing depends_on entries so the gateway calls the application "
                "service and the application service reaches the AI gateway, directly or "
                "through model admission.",
                [f"services.{gateway.id}.depends_on", f"services.{app.id}.depends_on"],
            )
        )
    if admission and ai_gateway:
        callers = [
            service.id
            for service in services.values()
            if admission.id in service.depends_on and service.id != admission.id
        ]
        if not callers:
            findings.append(
                _finding(
                    "ADMISSION_PATH",
                    f"No service depends on {admission.id}, so model admission and the hard "
                    "budget limit are not on any call path.",
                    f"Make the service that dispatches model calls depend on {admission.id} so "
                    "each attempt is reserved before dispatch.",
                    [f"services.{admission.id}", f"services.{ai_gateway.id}.depends_on"],
                )
            )
    findings.extend(retry_count_findings(design))
    findings.extend(workflow_reference_findings(design))
    findings.extend(guard_owner_findings(design))
    cycle = _cycle(services)
    if cycle:
        findings.append(
            _finding(
                "SERVICE_CYCLE",
                f"Services depend on each other in a cycle: {' → '.join(cycle)}. Startup "
                "readiness and the call direction between them are ambiguous.",
                "Keep one call direction between these services and remove the reverse "
                "depends_on entry.",
                [f"services.{name}.depends_on" for name in dict.fromkeys(cycle)],
            )
        )
    return findings
