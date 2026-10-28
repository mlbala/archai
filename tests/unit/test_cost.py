from decimal import Decimal

from archai.domain.cost import estimate_capacity, estimate_cost
from archai.ingestion import load_structured, parse_requirements
from archai.schemas.models import TargetEndpoint


def test_capacity_math_is_unit_explicit(requirements_file):
    requirements = parse_requirements(load_structured(requirements_file))
    result = estimate_capacity(requirements)
    assert result.calls_per_minute == Decimal("576.0")
    assert result.input_tokens_per_minute == Decimal("1036800.0")
    assert result.output_tokens_per_minute == Decimal("288000.0")
    assert result.worker_count == 7


def test_missing_price_produces_incomplete_subtotal(requirements_file):
    requirements = parse_requirements(load_structured(requirements_file))
    endpoint = TargetEndpoint(
        id="endpoint",
        provider="provider",
        deployment_id="deployment",
        region="westeurope",
        modalities=["text"],
        supports_tools=True,
        supports_schema=True,
        context_limit=100_000,
        rpm=100,
        tpm=100_000,
    )
    estimate = estimate_cost(requirements, endpoint)
    assert estimate.complete is False
    assert estimate.known_subtotal == 0
    assert len(estimate.warnings) == 3
