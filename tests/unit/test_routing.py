from archai.domain.routing import RouteRequest, eligible_routes, may_fallback
from archai.schemas.models import TargetEndpoint


def endpoint(**changes):
    values = {
        "id": "route-a",
        "provider": "managed",
        "deployment_id": "d",
        "region": "eu",
        "modalities": ["text"],
        "supports_tools": False,
        "supports_schema": True,
        "context_limit": 1000,
        "rpm": 10,
        "tpm": 1000,
    }
    values.update(changes)
    return TargetEndpoint.model_validate(values)


def test_route_filters_before_ranking():
    decision = eligible_routes(
        [endpoint(), endpoint(id="route-b", region="us", supports_tools=True)],
        RouteRequest(frozenset({"eu"}), "text", True, True, 900),
    )
    assert decision.eligible == ()
    assert decision.rejected == {"route-a": ("tools",), "route-b": ("residency",)}


def test_no_safety_fallback_or_stream_replay():
    assert may_fallback("safety_refusal", False) is False
    assert may_fallback("timeout", True) is False
    assert may_fallback("timeout", False) is True
