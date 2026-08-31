"""Live view of the pipelines, assembled from fulfillment status changes.

The studio never polls the order store. It subscribes to the service once and
folds every committed status change into an activity log and a set of counters,
so rendering a page is a read of already-derived state rather than a walk of
every order.

Everything here is thread-safe: the HTTP server answers on its own threads
while the stream loop writes from another.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

from fulfillment import FulfillmentService, Order, OrderStatus, StatusChange


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class ActivityEntry:
    """One committed status change, flattened for display."""

    at: str
    order_id: str
    buyer_handle: str
    summary: str
    from_status: str | None
    to_status: str
    reason: str
    total_cents: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "at": self.at,
            "order_id": self.order_id,
            "buyer_handle": self.buyer_handle,
            "summary": self.summary,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "reason": self.reason,
            "total_cents": self.total_cents,
        }


def describe_lines(order: Order, names: Mapping[str, str] | None = None) -> str:
    """Render an order's lines the way an operator reads them.

    Falls back to the raw SKU when no display name is configured, so a
    misconfigured catalog degrades to something still identifiable rather than
    to a blank.
    """
    names = names or {}
    parts = []
    for line in order.lines:
        label = names.get(line.sku, line.sku)
        parts.append(f"{line.quantity}x {label}" if line.quantity != 1 else label)
    return ", ".join(parts)


class StudioState:
    """Derived, always-current view of one fulfillment service.

    Construct it around the service the pipeline is already using — the same
    object ``CommerceBridge.service`` exposes — then call :meth:`attach` once.
    """

    def __init__(
        self,
        service: FulfillmentService,
        *,
        session_id: str = "live",
        names: Mapping[str, str] | None = None,
        activity_limit: int = 200,
    ) -> None:
        self.service = service
        self.session_id = session_id
        self.names = dict(names or {})
        self._lock = threading.RLock()
        self._activity: deque[ActivityEntry] = deque(maxlen=max(1, activity_limit))
        self._counts: dict[str, int] = {}
        self._started_at = time.monotonic()
        self._started_wall = datetime.now(timezone.utc)
        self._unsubscribe: Callable[[], None] | None = None

    # -- wiring ----------------------------------------------------------

    def attach(self) -> Callable[[], None]:
        """Subscribe to the service. Idempotent; returns the detach callable."""
        with self._lock:
            if self._unsubscribe is None:
                self._unsubscribe = self.service.subscribe(self.record)
            return self.detach

    def detach(self) -> None:
        with self._lock:
            if self._unsubscribe is not None:
                self._unsubscribe()
                self._unsubscribe = None

    @property
    def attached(self) -> bool:
        with self._lock:
            return self._unsubscribe is not None

    def set_session(self, session_id: str) -> None:
        with self._lock:
            self.session_id = session_id or "live"

    # -- ingest ----------------------------------------------------------

    def record(self, order: Order, change: StatusChange) -> None:
        """Fold one status change in. Registered as a service subscriber.

        Must not raise: the service isolates subscribers, but a listener that
        throws on every order would otherwise fill the log with noise.
        """
        try:
            entry = ActivityEntry(
                at=_iso(change.at),
                order_id=order.id,
                buyer_handle=order.buyer_handle,
                summary=describe_lines(order, self.names),
                from_status=change.from_status.value if change.from_status else None,
                to_status=change.to_status.value,
                reason=change.reason,
                total_cents=order.total_cents,
            )
        except Exception:  # noqa: BLE001 - never let the display break an order
            return
        with self._lock:
            self._activity.appendleft(entry)
            key = change.to_status.value
            self._counts[key] = self._counts.get(key, 0) + 1

    # -- reads -----------------------------------------------------------

    def activity(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return [e.as_dict() for e in list(self._activity)[: max(0, limit)]]

    def transition_counts(self) -> dict[str, int]:
        """How many times each status has been *entered*, not how many orders
        currently sit there — an order that reserved then fulfilled counts once
        in each."""
        with self._lock:
            return dict(self._counts)

    def uptime_seconds(self) -> float:
        return time.monotonic() - self._started_at

    def inventory_rows(self) -> list[dict[str, Any]]:
        rows = []
        for sku, level in sorted(self.service.inventory.snapshot().items()):
            rows.append(
                {
                    "sku": sku,
                    "name": self.names.get(sku, sku),
                    "on_hand": level.on_hand,
                    "reserved": level.reserved,
                    "available": level.available,
                }
            )
        return rows

    def order_rows(self, limit: int = 50, session_only: bool = True) -> list[dict[str, Any]]:
        with self._lock:
            session_id = self.session_id
            names = dict(self.names)
        orders: Iterable[Order] = (
            self.service.orders.for_session(session_id)
            if session_only
            else list(self.service.orders)
        )
        ordered = sorted(orders, key=lambda o: o.created_at, reverse=True)
        return [
            {
                "id": o.id,
                "buyer_handle": o.buyer_handle,
                "summary": describe_lines(o, names),
                "status": o.status.value,
                "units": o.unit_count,
                "total_cents": o.total_cents,
                "created_at": _iso(o.created_at),
                "updated_at": _iso(o.updated_at),
                "terminal": o.is_terminal,
                "holds_stock": o.holds_stock,
                "external_ref": o.external_ref,
                # Which controls the UI should offer, straight from the state
                # machine, so the page can never present an illegal action.
                "actions": [
                    status.value
                    for status in (
                        OrderStatus.FULFILLED,
                        OrderStatus.CANCELLED,
                        OrderStatus.FAILED,
                    )
                    if o.can_transition_to(status)
                ],
            }
            for o in ordered[: max(0, limit)]
        ]

    def snapshot(self, activity_limit: int = 50, order_limit: int = 50) -> dict[str, Any]:
        """Everything the page needs, in one read."""
        with self._lock:
            session_id = self.session_id
        inventory = self.inventory_rows()
        return {
            "generated_at": _iso(datetime.now(timezone.utc)),
            "started_at": _iso(self._started_wall),
            "uptime_seconds": round(self.uptime_seconds(), 1),
            "session_id": session_id,
            "attached": self.attached,
            "summary": self.service.session_summary(session_id),
            "transitions": self.transition_counts(),
            "orders": self.order_rows(limit=order_limit),
            "inventory": inventory,
            "activity": self.activity(limit=activity_limit),
            "alerts": self.alerts(inventory),
        }

    def alerts(self, inventory: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
        """Conditions an operator should see without reading the tables.

        Deliberately few: an alert that fires constantly is one nobody reads.
        """
        rows = inventory if inventory is not None else self.inventory_rows()
        alerts: list[dict[str, str]] = []

        sold_out = [r["name"] for r in rows if r["available"] == 0 and r["on_hand"] > 0]
        if sold_out:
            alerts.append(
                {
                    "level": "warning",
                    "text": f"No units available: {', '.join(sold_out)}",
                }
            )
        empty = [r["name"] for r in rows if r["on_hand"] == 0]
        if empty:
            alerts.append(
                {"level": "info", "text": f"Out of stock: {', '.join(empty)}"}
            )
        if not self.attached:
            alerts.append(
                {
                    "level": "warning",
                    "text": "Not subscribed to the fulfillment service — activity is not being recorded.",
                }
            )
        return alerts
