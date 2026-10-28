from __future__ import annotations

from dataclasses import dataclass

from archai.schemas.models import TargetEndpoint


@dataclass(frozen=True)
class RouteRequest:
    regions: frozenset[str]
    modality: str
    tools: bool
    schema: bool
    context_tokens: int


@dataclass(frozen=True)
class RouteDecision:
    eligible: tuple[str, ...]
    rejected: dict[str, tuple[str, ...]]


def eligible_routes(endpoints: list[TargetEndpoint], request: RouteRequest) -> RouteDecision:
    eligible: list[str] = []
    rejected: dict[str, tuple[str, ...]] = {}
    for endpoint in endpoints:
        reasons: list[str] = []
        if endpoint.region not in request.regions:
            reasons.append("residency")
        if request.modality not in endpoint.modalities:
            reasons.append("modality")
        if request.tools and not endpoint.supports_tools:
            reasons.append("tools")
        if request.schema and not endpoint.supports_schema:
            reasons.append("schema")
        if request.context_tokens > endpoint.context_limit:
            reasons.append("context")
        if reasons:
            rejected[endpoint.id] = tuple(reasons)
        else:
            eligible.append(endpoint.id)
    return RouteDecision(tuple(eligible), rejected)


def may_fallback(error_class: str, stream_started: bool) -> bool:
    if stream_started:
        return False
    return error_class in {"timeout", "rate_limit", "server_error"}
