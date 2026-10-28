from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

from archai.schemas.models import (
    CapacityResult,
    CostEstimate,
    CostLineItem,
    RequirementsSpec,
    TargetEndpoint,
)

MILLION = Decimal(1_000_000)
SECONDS_PER_MONTH = Decimal(30 * 24 * 60 * 60)


def estimate_capacity(
    requirements: RequirementsSpec,
    *,
    service_seconds: Decimal = Decimal("2"),
    parallel_jobs_per_worker: Decimal = Decimal("4"),
    target_utilization: Decimal = Decimal("0.7"),
) -> CapacityResult:
    calls_per_minute = requirements.peak_rps * 60 * requirements.model_calls_per_request
    input_tpm = calls_per_minute * requirements.input_tokens
    output_tpm = calls_per_minute * requirements.output_tokens
    workers = (
        requirements.peak_rps
        * requirements.model_calls_per_request
        * service_seconds
        / (parallel_jobs_per_worker * target_utilization)
    ).to_integral_value(rounding=ROUND_CEILING)
    return CapacityResult(
        calls_per_minute=calls_per_minute,
        input_tokens_per_minute=input_tpm,
        output_tokens_per_minute=output_tpm,
        worker_count=int(workers),
    )


def estimate_cost(
    requirements: RequirementsSpec,
    endpoint: TargetEndpoint,
    *,
    scenario: str = "baseline",
    rps: Decimal | None = None,
    attempts: Decimal = Decimal(1),
) -> CostEstimate:
    """Monthly managed-model token cost if the given request rate were sustained all month.

    ``attempts`` multiplies calls to model retries or fallback attempts. Unknown prices produce
    a known subtotal plus warnings rather than a false zero total.
    """
    rate = rps if rps is not None else requirements.avg_rps
    monthly_calls = rate * SECONDS_PER_MONTH * requirements.model_calls_per_request * attempts
    inputs = monthly_calls * requirements.input_tokens
    outputs = monthly_calls * requirements.output_tokens
    items: list[CostLineItem] = []
    warnings: list[str] = []
    known = Decimal(0)
    for name, quantity, price in (
        ("managed-model input", inputs / MILLION, endpoint.input_price_per_million),
        ("managed-model output", outputs / MILLION, endpoint.output_price_per_million),
    ):
        subtotal = quantity * price if price is not None else None
        if subtotal is None:
            warnings.append(f"Missing price for {name}")
        else:
            known += subtotal
        items.append(
            CostLineItem(
                name=name,
                quantity=quantity,
                unit="million_tokens",
                unit_price=price,
                currency=requirements.currency,
                subtotal=subtotal,
                source=f"{endpoint.id} project input; not a live quotation",
            )
        )
    warnings.append("Cloud compute, data, telemetry, and network prices require account rate cards")
    return CostEstimate(
        scenario=scenario,
        currency=requirements.currency,
        known_subtotal=known,
        complete=False,
        items=items,
        warnings=warnings,
    )
