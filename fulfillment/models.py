"""Core value types: order lines, orders, and the order state machine."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable, Mapping

from .errors import InvalidTransition, ValidationError


def utcnow() -> datetime:
    """Timezone-aware UTC now. Centralised so tests can monkeypatch one symbol."""
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class OrderStatus(str, Enum):
    """Lifecycle of an order.

    ``CAPTURED`` means recorded but holding no stock; ``RESERVED`` means stock
    is held for it; ``FULFILLED`` means that hold was converted into a real
    depletion.

    ``CANCELLED`` and ``FAILED`` are both terminal and both release any hold,
    but they are not interchangeable: ``CANCELLED`` records a decision (the
    buyer or an operator pulled the order), while ``FAILED`` records a system
    outcome (payment declined, downstream fulfillment errored). A reserved
    order can reach either, since a charge can fail after stock is held.
    """

    CAPTURED = "captured"
    RESERVED = "reserved"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"
    FAILED = "failed"


#: Legal status transitions. A status absent from a value set is unreachable
#: from that key, and an empty set marks a terminal status.
ALLOWED_TRANSITIONS: Mapping[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.CAPTURED: frozenset(
        {OrderStatus.RESERVED, OrderStatus.CANCELLED, OrderStatus.FAILED}
    ),
    OrderStatus.RESERVED: frozenset(
        {OrderStatus.FULFILLED, OrderStatus.CANCELLED, OrderStatus.FAILED}
    ),
    OrderStatus.FULFILLED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.FAILED: frozenset(),
}

#: Statuses that still hold a stock reservation.
HOLDING_STATUSES = frozenset({OrderStatus.RESERVED})

#: Statuses no further transition can leave.
TERMINAL_STATUSES = frozenset(
    status for status, allowed in ALLOWED_TRANSITIONS.items() if not allowed
)


@dataclass(frozen=True, slots=True)
class OrderLine:
    """A single SKU and quantity within an order."""

    sku: str
    quantity: int
    unit_price_cents: int = 0

    def __post_init__(self) -> None:
        if not self.sku or not self.sku.strip():
            raise ValidationError("order line sku must be a non-empty string")
        if not isinstance(self.quantity, int) or isinstance(self.quantity, bool):
            raise ValidationError("order line quantity must be an int")
        if self.quantity <= 0:
            raise ValidationError(
                f"order line quantity must be positive, got {self.quantity}"
            )
        if self.unit_price_cents < 0:
            raise ValidationError(
                f"order line unit_price_cents cannot be negative, got {self.unit_price_cents}"
            )

    @property
    def subtotal_cents(self) -> int:
        return self.quantity * self.unit_price_cents


@dataclass(frozen=True, slots=True)
class StatusChange:
    """One entry in an order's audit trail."""

    at: datetime
    from_status: OrderStatus | None
    to_status: OrderStatus
    reason: str = ""


@dataclass(slots=True)
class Order:
    """An order captured from a live session.

    ``external_ref`` is the caller's own identifier for the originating event
    (a chat message id, a checkout token). It is the idempotency key: capturing
    twice with the same ref returns the first order rather than creating a
    second one.
    """

    session_id: str
    lines: tuple[OrderLine, ...]
    buyer_handle: str = ""
    external_ref: str | None = None
    id: str = field(default_factory=lambda: new_id("ord"))
    status: OrderStatus = OrderStatus.CAPTURED
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    history: tuple[StatusChange, ...] = ()

    def __post_init__(self) -> None:
        if not self.session_id or not self.session_id.strip():
            raise ValidationError("order session_id must be a non-empty string")
        self.lines = tuple(self.lines)
        if not self.lines:
            raise ValidationError("order must contain at least one line")
        if not self.history:
            self.history = (
                StatusChange(
                    at=self.created_at,
                    from_status=None,
                    to_status=self.status,
                    reason="captured",
                ),
            )

    @property
    def total_cents(self) -> int:
        return sum(line.subtotal_cents for line in self.lines)

    @property
    def unit_count(self) -> int:
        return sum(line.quantity for line in self.lines)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def holds_stock(self) -> bool:
        return self.status in HOLDING_STATUSES

    def can_transition_to(self, target: OrderStatus) -> bool:
        return target in ALLOWED_TRANSITIONS[self.status]

    def transition_to(self, target: OrderStatus, reason: str = "") -> StatusChange:
        """Move to ``target``, appending to the audit trail.

        Raises :class:`InvalidTransition` if the move is not legal from the
        current status. Mutates in place and returns the recorded change.
        """
        if not self.can_transition_to(target):
            raise InvalidTransition(self.id, self.status.value, target.value)
        change = StatusChange(
            at=utcnow(), from_status=self.status, to_status=target, reason=reason
        )
        self.status = target
        self.updated_at = change.at
        self.history = self.history + (change,)
        return change


def merge_lines(lines: Iterable[OrderLine]) -> tuple[OrderLine, ...]:
    """Collapse repeated SKUs into one line each, summing quantities.

    Live capture routinely produces several lines for the same SKU (a viewer
    taps buy three times). Merging before reserving means the inventory sees
    one total per SKU instead of racing partial holds against itself.
    """
    totals: dict[str, int] = {}
    prices: dict[str, int] = {}
    for line in lines:
        totals[line.sku] = totals.get(line.sku, 0) + line.quantity
        prices.setdefault(line.sku, line.unit_price_cents)
    return tuple(
        OrderLine(sku=sku, quantity=qty, unit_price_cents=prices[sku])
        for sku, qty in totals.items()
    )
