"""Exception hierarchy for the fulfillment module.

Every error raised by this package derives from :class:`FulfillmentError`, so
callers embedding fulfillment inside a live-stream event loop can catch a
single base class and keep the stream running.
"""

from __future__ import annotations


class FulfillmentError(Exception):
    """Base class for every error raised by this package."""


class ValidationError(FulfillmentError):
    """A value supplied by the caller is structurally invalid."""


class UnknownSku(FulfillmentError):
    """A SKU was referenced that the inventory has never seen."""

    def __init__(self, sku: str) -> None:
        super().__init__(f"unknown sku: {sku!r}")
        self.sku = sku


class InsufficientStock(FulfillmentError):
    """A reservation asked for more units than are available."""

    def __init__(self, sku: str, requested: int, available: int) -> None:
        super().__init__(
            f"insufficient stock for {sku!r}: requested {requested}, available {available}"
        )
        self.sku = sku
        self.requested = requested
        self.available = available


class UnknownOrder(FulfillmentError):
    """An order id was referenced that the store does not hold."""

    def __init__(self, order_id: str) -> None:
        super().__init__(f"unknown order: {order_id!r}")
        self.order_id = order_id


class InvalidTransition(FulfillmentError):
    """An order was asked to move to a status it cannot legally reach."""

    def __init__(self, order_id: str, current: str, target: str) -> None:
        super().__init__(
            f"order {order_id!r} cannot move from {current} to {target}"
        )
        self.order_id = order_id
        self.current = current
        self.target = target
