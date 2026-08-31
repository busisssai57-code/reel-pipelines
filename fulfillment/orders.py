"""Thread-safe order storage with an idempotency index."""

from __future__ import annotations

import threading
from typing import Callable, Iterator

from .errors import UnknownOrder
from .models import Order, OrderStatus


class OrderStore:
    """In-memory order book, safe for concurrent use.

    Alongside the id index it keeps an ``external_ref`` index so repeated
    delivery of the same live event resolves to the order already created for
    it rather than a duplicate. As with :class:`~fulfillment.inventory.InventoryStore`,
    this is the reference implementation of an interface a durable backend is
    expected to satisfy.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._orders: dict[str, Order] = {}
        self._by_ref: dict[str, str] = {}

    def __len__(self) -> int:
        with self._lock:
            return len(self._orders)

    def __iter__(self) -> Iterator[Order]:
        with self._lock:
            return iter(list(self._orders.values()))

    def add(self, order: Order) -> Order:
        with self._lock:
            self._orders[order.id] = order
            if order.external_ref is not None:
                self._by_ref[order.external_ref] = order.id
            return order

    def get(self, order_id: str) -> Order:
        """Return the order or raise :class:`UnknownOrder`."""
        with self._lock:
            try:
                return self._orders[order_id]
            except KeyError:
                raise UnknownOrder(order_id) from None

    def find(self, order_id: str) -> Order | None:
        with self._lock:
            return self._orders.get(order_id)

    def by_external_ref(self, external_ref: str) -> Order | None:
        with self._lock:
            order_id = self._by_ref.get(external_ref)
            return self._orders.get(order_id) if order_id else None

    def where(self, predicate: Callable[[Order], bool]) -> list[Order]:
        with self._lock:
            return [o for o in self._orders.values() if predicate(o)]

    def for_session(self, session_id: str) -> list[Order]:
        return self.where(lambda o: o.session_id == session_id)

    def open_for_session(self, session_id: str) -> list[Order]:
        """Orders in this session that have not reached a terminal status."""
        return self.where(
            lambda o: o.session_id == session_id and not o.is_terminal
        )

    def with_status(self, status: OrderStatus) -> list[Order]:
        return self.where(lambda o: o.status is status)
