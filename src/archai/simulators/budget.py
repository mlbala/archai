from __future__ import annotations

import threading
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class ReservationState(StrEnum):
    reserved = "reserved"
    dispatched = "dispatched"
    settled = "settled"
    unresolved = "unresolved"
    reconciled = "reconciled"
    released = "released"


@dataclass
class Reservation:
    id: str
    amount: Decimal
    state: ReservationState
    actual: Decimal | None = None


class BudgetLedger:
    """Thread-safe reference state machine, not a production distributed ledger."""

    def __init__(self, limit: Decimal) -> None:
        self.limit = limit
        self._reservations: dict[str, Reservation] = {}
        self._lock = threading.Lock()
        self.available = True

    @property
    def liability(self) -> Decimal:
        return sum(
            (
                reservation.actual
                if reservation.state in {ReservationState.settled, ReservationState.reconciled}
                and reservation.actual is not None
                else reservation.amount
                for reservation in self._reservations.values()
                if reservation.state != ReservationState.released
            ),
            Decimal(0),
        )

    def reserve(self, reservation_id: str, amount: Decimal) -> bool:
        if amount <= 0:
            raise ValueError("reservation amount must be positive")
        with self._lock:
            if not self.available:
                return False
            existing = self._reservations.get(reservation_id)
            if existing is not None:
                return existing.amount == amount
            if self.liability + amount > self.limit:
                return False
            self._reservations[reservation_id] = Reservation(
                reservation_id, amount, ReservationState.reserved
            )
            return True

    def dispatch(self, reservation_id: str) -> None:
        with self._lock:
            reservation = self._reservations[reservation_id]
            if reservation.state != ReservationState.reserved:
                raise ValueError("only a reserved attempt may be dispatched")
            reservation.state = ReservationState.dispatched

    def settle(self, reservation_id: str, actual: Decimal) -> None:
        with self._lock:
            reservation = self._reservations[reservation_id]
            if reservation.state == ReservationState.settled:
                if reservation.actual != actual:
                    raise ValueError("duplicate settlement amount differs")
                return
            if reservation.state not in {ReservationState.dispatched, ReservationState.unresolved}:
                raise ValueError("attempt is not settleable")
            if actual < 0 or actual > reservation.amount:
                raise ValueError("actual must fit within the reserved upper bound")
            reservation.actual = actual
            reservation.state = ReservationState.settled

    def mark_unresolved(self, reservation_id: str) -> None:
        with self._lock:
            reservation = self._reservations[reservation_id]
            if reservation.state != ReservationState.dispatched:
                raise ValueError("only a dispatched attempt may become unresolved")
            reservation.state = ReservationState.unresolved

    def release(self, reservation_id: str) -> None:
        with self._lock:
            reservation = self._reservations[reservation_id]
            if reservation.state != ReservationState.reserved:
                raise ValueError("dispatched liability cannot be released")
            reservation.state = ReservationState.released
