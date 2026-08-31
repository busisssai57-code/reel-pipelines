"""Thread-safe inventory with two-phase (reserve then commit) stock control.

A live drop puts many concurrent buyers against a small stock count, so the
window between "we checked availability" and "we took the units" is exactly
where overselling happens. This store closes that window by holding a
*reservation* under the same lock that checked availability, and only
depleting on-hand units when the order actually fulfils.

For every SKU::

    available = on_hand - reserved

Reservations across several SKUs are all-or-nothing: a basket that cannot be
satisfied in full holds nothing at all, so a partially-stocked basket never
strands units that another buyer could have had.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Iterable, Mapping

from .errors import InsufficientStock, UnknownSku, ValidationError
from .models import OrderLine, merge_lines


@dataclass(frozen=True, slots=True)
class StockLevel:
    """An immutable snapshot of one SKU's position."""

    sku: str
    on_hand: int
    reserved: int

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved


class InventoryStore:
    """In-memory stock ledger, safe for concurrent use.

    This is the reference implementation and the interface a durable backend
    (Postgres, Redis, a supplier API) is expected to satisfy. Callers should
    depend on the method surface, not on the fact that it is a dict today.
    """

    def __init__(self, initial: Mapping[str, int] | None = None) -> None:
        self._lock = threading.RLock()
        self._on_hand: dict[str, int] = {}
        self._reserved: dict[str, int] = {}
        for sku, qty in (initial or {}).items():
            self.add_product(sku, qty)

    # -- registration ----------------------------------------------------

    def add_product(self, sku: str, on_hand: int = 0) -> None:
        """Register a SKU, or raise if it already exists."""
        if not sku or not sku.strip():
            raise ValidationError("sku must be a non-empty string")
        if on_hand < 0:
            raise ValidationError(f"on_hand cannot be negative, got {on_hand}")
        with self._lock:
            if sku in self._on_hand:
                raise ValidationError(f"sku {sku!r} is already registered")
            self._on_hand[sku] = on_hand
            self._reserved[sku] = 0

    def restock(self, sku: str, quantity: int) -> int:
        """Add units to a known SKU and return the new on-hand count."""
        if quantity <= 0:
            raise ValidationError(f"restock quantity must be positive, got {quantity}")
        with self._lock:
            self._require(sku)
            self._on_hand[sku] += quantity
            return self._on_hand[sku]

    def sync(self, levels: Mapping[str, int]) -> dict[str, int]:
        """Reconcile on-hand counts against an external source of truth.

        Unknown SKUs are registered. Returns the SKUs whose on-hand count moved,
        mapped to the delta, so a caller can log or alert on drift.

        A sync that would drop on-hand below the units already reserved is
        rejected for that SKU: those units are promised to live buyers, and
        silently invalidating their holds would oversell after the fact.
        """
        drift: dict[str, int] = {}
        with self._lock:
            for sku, count in levels.items():
                if count < 0:
                    raise ValidationError(f"sync count for {sku!r} cannot be negative")
                if sku not in self._on_hand:
                    self._on_hand[sku] = 0
                    self._reserved[sku] = 0
                held = self._reserved[sku]
                if count < held:
                    raise ValidationError(
                        f"sync would set {sku!r} on_hand to {count} "
                        f"below {held} already-reserved units"
                    )
                delta = count - self._on_hand[sku]
                if delta:
                    self._on_hand[sku] = count
                    drift[sku] = delta
        return drift

    # -- reads -----------------------------------------------------------

    def available(self, sku: str) -> int:
        with self._lock:
            self._require(sku)
            return self._on_hand[sku] - self._reserved[sku]

    def level(self, sku: str) -> StockLevel:
        with self._lock:
            self._require(sku)
            return StockLevel(sku, self._on_hand[sku], self._reserved[sku])

    def snapshot(self) -> dict[str, StockLevel]:
        with self._lock:
            return {
                sku: StockLevel(sku, on_hand, self._reserved[sku])
                for sku, on_hand in self._on_hand.items()
            }

    def knows(self, sku: str) -> bool:
        with self._lock:
            return sku in self._on_hand

    # -- two-phase stock control -----------------------------------------

    def reserve(self, lines: Iterable[OrderLine]) -> None:
        """Hold stock for every line, all-or-nothing.

        Raises :class:`UnknownSku` or :class:`InsufficientStock` without
        holding anything if any line cannot be satisfied.
        """
        merged = merge_lines(lines)
        with self._lock:
            for line in merged:
                self._require(line.sku)
                free = self._on_hand[line.sku] - self._reserved[line.sku]
                if line.quantity > free:
                    raise InsufficientStock(line.sku, line.quantity, free)
            for line in merged:
                self._reserved[line.sku] += line.quantity

    def release(self, lines: Iterable[OrderLine]) -> None:
        """Drop a hold without depleting stock (cancellation, expiry)."""
        merged = merge_lines(lines)
        with self._lock:
            for line in merged:
                self._require(line.sku)
                if line.quantity > self._reserved[line.sku]:
                    raise ValidationError(
                        f"cannot release {line.quantity} of {line.sku!r}: "
                        f"only {self._reserved[line.sku]} reserved"
                    )
            for line in merged:
                self._reserved[line.sku] -= line.quantity

    def commit(self, lines: Iterable[OrderLine]) -> None:
        """Convert a hold into a real depletion (the goods shipped)."""
        merged = merge_lines(lines)
        with self._lock:
            for line in merged:
                self._require(line.sku)
                if line.quantity > self._reserved[line.sku]:
                    raise ValidationError(
                        f"cannot commit {line.quantity} of {line.sku!r}: "
                        f"only {self._reserved[line.sku]} reserved"
                    )
            for line in merged:
                self._reserved[line.sku] -= line.quantity
                self._on_hand[line.sku] -= line.quantity

    # -- internal --------------------------------------------------------

    def _require(self, sku: str) -> None:
        """Assert the SKU is known. Caller must already hold the lock."""
        if sku not in self._on_hand:
            raise UnknownSku(sku)
