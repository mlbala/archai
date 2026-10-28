from decimal import Decimal
from threading import Thread

import pytest

from archai.simulators.budget import BudgetLedger


def test_concurrent_reservations_cannot_exceed_limit():
    ledger = BudgetLedger(Decimal("10"))
    results = []
    threads = [
        Thread(target=lambda key=key: results.append(ledger.reserve(key, Decimal("7"))))
        for key in ("a", "b")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == [False, True]
    assert ledger.liability == Decimal("7")


def test_uncertain_dispatch_retains_liability_and_settlement_is_idempotent():
    ledger = BudgetLedger(Decimal("10"))
    assert ledger.reserve("a", Decimal("7"))
    ledger.dispatch("a")
    ledger.mark_unresolved("a")
    assert ledger.liability == Decimal("7")
    with pytest.raises(ValueError):
        ledger.release("a")
    ledger.settle("a", Decimal("5"))
    ledger.settle("a", Decimal("5"))
    assert ledger.liability == Decimal("5")


def test_budget_authority_outage_fails_closed():
    ledger = BudgetLedger(Decimal("10"))
    ledger.available = False
    assert ledger.reserve("a", Decimal("1")) is False
