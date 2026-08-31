"""The fulfillment service and its live-session event seam.

Two call styles, deliberately different in how they fail:

* The direct API (:meth:`FulfillmentService.capture`, :meth:`fulfill`,
  :meth:`cancel`) raises. Use it when the caller can handle an exception.
* :meth:`FulfillmentService.handle_live_event` never raises. It is the
  boundary the stream loop calls, where an out-of-stock buyer must not be able
  to take the broadcast down. Failures come back as an :class:`EventResult`
  with ``ok`` false and a populated ``error``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable, Mapping, Sequence

from .errors import FulfillmentError, InvalidTransition, ValidationError
from .inventory import InventoryStore
from .models import Order, OrderLine, OrderStatus, StatusChange
from .orders import OrderStore

#: Called after every committed status change. Must not raise; exceptions are
#: swallowed so one bad subscriber cannot break order processing.
StatusListener = Callable[[Order, StatusChange], None]


class LiveEventKind(str, Enum):
    """Live-session events this module reacts to."""

    ORDER_PLACED = "order_placed"
    ORDER_CANCELLED = "order_cancelled"
    STOCK_SYNC = "stock_sync"
    SESSION_ENDED = "session_ended"


@dataclass(frozen=True, slots=True)
class LiveEvent:
    """An event emitted by the streaming side.

    Intentionally a plain dataclass with a ``dict`` payload: the fulfillment
    package imports nothing from the streamer, so the two modules can be built
    and tested independently. The streamer adapts its own event type to this
    one at the boundary.

    ``external_ref`` is the idempotency key. Re-delivering an event that
    carries one is a no-op that returns the original order.
    """

    kind: LiveEventKind
    session_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    external_ref: str | None = None


@dataclass(frozen=True, slots=True)
class EventResult:
    """Outcome of :meth:`FulfillmentService.handle_live_event`."""

    ok: bool
    kind: LiveEventKind
    order: Order | None = None
    error: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)
    duplicate: bool = False


def lines_from_payload(payload: Mapping[str, Any]) -> tuple[OrderLine, ...]:
    """Build order lines from a live event payload.

    Accepts either a single ``sku``/``quantity`` pair or a ``lines`` list of
    mappings, since streaming sources emit both shapes.
    """
    raw: Sequence[Mapping[str, Any]]
    if "lines" in payload:
        candidate = payload["lines"]
        if not isinstance(candidate, Sequence) or isinstance(candidate, (str, bytes)):
            raise ValidationError("payload 'lines' must be a list of mappings")
        raw = candidate
    elif "sku" in payload:
        raw = [payload]
    else:
        raise ValidationError("payload must contain either 'lines' or 'sku'")

    if not raw:
        raise ValidationError("payload contained no order lines")

    built = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValidationError("each order line must be a mapping")
        if "sku" not in item:
            raise ValidationError("each order line requires a 'sku'")
        built.append(
            OrderLine(
                sku=str(item["sku"]),
                quantity=int(item.get("quantity", 1)),
                unit_price_cents=int(item.get("unit_price_cents", 0)),
            )
        )
    return tuple(built)


class FulfillmentService:
    """Order capture, stock control, and fulfillment triggers."""

    def __init__(
        self,
        inventory: InventoryStore | None = None,
        orders: OrderStore | None = None,
    ) -> None:
        self.inventory = inventory if inventory is not None else InventoryStore()
        self.orders = orders if orders is not None else OrderStore()
        self._lock = threading.RLock()
        self._listeners: list[StatusListener] = []

    # -- observation -----------------------------------------------------

    def subscribe(self, listener: StatusListener) -> Callable[[], None]:
        """Register a status-change listener; returns an unsubscribe callable.

        This is the seam the dashboard and the streamer overlay read from —
        neither needs to poll the order store.
        """
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def _emit(self, order: Order, change: StatusChange) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(order, change)
            except Exception:  # noqa: BLE001 - a subscriber must never break an order
                pass

    # -- direct API (raises) ---------------------------------------------

    def capture(
        self,
        session_id: str,
        lines: Iterable[OrderLine],
        buyer_handle: str = "",
        external_ref: str | None = None,
        reserve: bool = True,
    ) -> Order:
        """Record an order and, by default, hold stock for it.

        Idempotent on ``external_ref``: a repeat call with a ref already seen
        returns the existing order untouched, without reserving twice.
        """
        with self._lock:
            if external_ref is not None:
                existing = self.orders.by_external_ref(external_ref)
                if existing is not None:
                    return existing

            order = Order(
                session_id=session_id,
                lines=tuple(lines),
                buyer_handle=buyer_handle,
                external_ref=external_ref,
            )

            if not reserve:
                return self.orders.add(order)

            # Reserve before the order is visible in the store, so a failed
            # capture leaves behind neither a hold nor a phantom order.
            self.inventory.reserve(order.lines)
            try:
                change = order.transition_to(OrderStatus.RESERVED, "stock held")
                self.orders.add(order)
            except Exception:
                self.inventory.release(order.lines)
                raise

        self._emit(order, change)
        return order

    def fulfill(self, order_id: str, reason: str = "fulfilled") -> Order:
        """Convert an order's hold into a real depletion."""
        with self._lock:
            order = self.orders.get(order_id)
            # Validate the transition before touching stock: commit() is not
            # reversible by reserve() (it moves on-hand as well as the hold),
            # so there must be nothing left to fail after it runs.
            if not order.can_transition_to(OrderStatus.FULFILLED):
                raise InvalidTransition(
                    order.id, order.status.value, OrderStatus.FULFILLED.value
                )
            self.inventory.commit(order.lines)
            change = order.transition_to(OrderStatus.FULFILLED, reason)
        self._emit(order, change)
        return order

    def cancel(self, order_id: str, reason: str = "cancelled") -> Order:
        """Cancel an order, releasing any stock it holds."""
        with self._lock:
            order = self.orders.get(order_id)
            held = order.holds_stock
            change = order.transition_to(OrderStatus.CANCELLED, reason)
            if held:
                self.inventory.release(order.lines)
        self._emit(order, change)
        return order

    def mark_failed(self, order_id: str, reason: str) -> Order:
        """Mark an order failed by a system outcome, releasing any hold.

        Use this rather than :meth:`cancel` when the order died on a payment
        decline or a downstream error, so reporting can separate lost sales
        from deliberate cancellations.
        """
        with self._lock:
            order = self.orders.get(order_id)
            held = order.holds_stock
            change = order.transition_to(OrderStatus.FAILED, reason)
            if held:
                self.inventory.release(order.lines)
        self._emit(order, change)
        return order

    def release_open_holds(self, session_id: str, reason: str = "session ended") -> list[Order]:
        """Cancel every still-open order in a session, freeing its stock.

        Not called automatically on ``SESSION_ENDED`` — dropping a paid buyer's
        hold is a policy decision, so the caller makes it explicitly.
        """
        cancelled = []
        for order in self.orders.open_for_session(session_id):
            cancelled.append(self.cancel(order.id, reason))
        return cancelled

    def session_summary(self, session_id: str) -> dict[str, Any]:
        """Aggregate a session's order book, for the dashboard and reporting."""
        orders = self.orders.for_session(session_id)
        by_status: dict[str, int] = {}
        for order in orders:
            by_status[order.status.value] = by_status.get(order.status.value, 0) + 1
        realised = [o for o in orders if o.status is OrderStatus.FULFILLED]
        return {
            "session_id": session_id,
            "orders": len(orders),
            "by_status": by_status,
            "units_fulfilled": sum(o.unit_count for o in realised),
            "revenue_cents": sum(o.total_cents for o in realised),
            "open_orders": len([o for o in orders if not o.is_terminal]),
        }

    # -- live event seam (never raises) ----------------------------------

    def handle_live_event(self, event: LiveEvent) -> EventResult:
        """Apply a live-session event. Returns an outcome instead of raising."""
        try:
            if event.kind is LiveEventKind.ORDER_PLACED:
                return self._on_order_placed(event)
            if event.kind is LiveEventKind.ORDER_CANCELLED:
                return self._on_order_cancelled(event)
            if event.kind is LiveEventKind.STOCK_SYNC:
                return self._on_stock_sync(event)
            if event.kind is LiveEventKind.SESSION_ENDED:
                return EventResult(
                    ok=True,
                    kind=event.kind,
                    detail=self.session_summary(event.session_id),
                )
            return EventResult(
                ok=False, kind=event.kind, error=f"unhandled event kind: {event.kind}"
            )
        except FulfillmentError as exc:
            return EventResult(
                ok=False,
                kind=event.kind,
                error=str(exc),
                detail={"error_type": type(exc).__name__},
            )
        except Exception as exc:  # noqa: BLE001 - the stream loop must survive
            return EventResult(
                ok=False,
                kind=event.kind,
                error=f"unexpected error: {exc}",
                detail={"error_type": type(exc).__name__},
            )

    def _on_order_placed(self, event: LiveEvent) -> EventResult:
        if event.external_ref is not None:
            existing = self.orders.by_external_ref(event.external_ref)
            if existing is not None:
                return EventResult(
                    ok=True, kind=event.kind, order=existing, duplicate=True
                )
        lines = lines_from_payload(event.payload)
        order = self.capture(
            session_id=event.session_id,
            lines=lines,
            buyer_handle=str(event.payload.get("buyer_handle", "")),
            external_ref=event.external_ref,
        )
        return EventResult(ok=True, kind=event.kind, order=order)

    def _on_order_cancelled(self, event: LiveEvent) -> EventResult:
        order_id = event.payload.get("order_id")
        if not order_id and event.external_ref:
            found = self.orders.by_external_ref(event.external_ref)
            order_id = found.id if found else None
        if not order_id:
            raise ValidationError(
                "order_cancelled requires payload 'order_id' or a known external_ref"
            )
        order = self.cancel(
            str(order_id), str(event.payload.get("reason", "cancelled from live"))
        )
        return EventResult(ok=True, kind=event.kind, order=order)

    def _on_stock_sync(self, event: LiveEvent) -> EventResult:
        levels = event.payload.get("levels")
        if not isinstance(levels, Mapping):
            raise ValidationError("stock_sync requires a 'levels' mapping")
        drift = self.inventory.sync({str(k): int(v) for k, v in levels.items()})
        return EventResult(ok=True, kind=event.kind, detail={"drift": drift})
