from __future__ import annotations

from decimal import Decimal
from typing import Any

from archai.domain.routing import may_fallback
from archai.simulators.budget import BudgetLedger


def simulate_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    limit = Decimal(str(scenario.get("budget_limit", "10")))
    ledger = BudgetLedger(limit)
    attempts: list[dict[str, Any]] = []
    stream_started = bool(scenario.get("stream_started", False))
    for index, item in enumerate(scenario.get("attempts", []), start=1):
        amount = Decimal(str(item.get("reserve", "1")))
        attempt_id = str(item.get("id", f"attempt-{index}"))
        accepted = ledger.reserve(attempt_id, amount)
        result: dict[str, Any] = {"id": attempt_id, "reserved": accepted}
        if not accepted:
            attempts.append(result)
            break
        ledger.dispatch(attempt_id)
        error = item.get("error")
        if error:
            ledger.mark_unresolved(attempt_id)
            result["fallback_allowed"] = may_fallback(str(error), stream_started)
            attempts.append(result)
            if not result["fallback_allowed"]:
                break
        else:
            actual = Decimal(str(item.get("actual", amount)))
            ledger.settle(attempt_id, actual)
            result["settled"] = str(actual)
            attempts.append(result)
            break
    return {
        "budget_limit": str(limit),
        "liability": str(ledger.liability),
        "attempts": attempts,
        "note": "Local deterministic reference simulation; no provider was called.",
    }
