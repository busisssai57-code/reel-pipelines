"""BTA product fulfillment: order capture, inventory sync, fulfillment triggers.

Wiring a live session to fulfillment::

    from fulfillment import FulfillmentService, InventoryStore, LiveEvent, LiveEventKind

    service = FulfillmentService(InventoryStore({"tee-blk-l": 40}))

    result = service.handle_live_event(LiveEvent(
        kind=LiveEventKind.ORDER_PLACED,
        session_id="live-2026-08-31",
        payload={"sku": "tee-blk-l", "quantity": 2, "buyer_handle": "@viewer"},
        external_ref="comment-8823",     # idempotency key
    ))
    if result.ok:
        service.fulfill(result.order.id)

``handle_live_event`` never raises, so the stream loop cannot be taken down by
a bad order. The direct methods (``capture``/``fulfill``/``cancel``) do raise.
"""

from .errors import (
    FulfillmentError,
    InsufficientStock,
    InvalidTransition,
    UnknownOrder,
    UnknownSku,
    ValidationError,
)
from .inventory import InventoryStore, StockLevel
from .models import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    Order,
    OrderLine,
    OrderStatus,
    StatusChange,
    merge_lines,
)
from .orders import OrderStore
from .service import (
    EventResult,
    FulfillmentService,
    LiveEvent,
    LiveEventKind,
    StatusListener,
    lines_from_payload,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "TERMINAL_STATUSES",
    "EventResult",
    "FulfillmentError",
    "FulfillmentService",
    "InsufficientStock",
    "InvalidTransition",
    "InventoryStore",
    "LiveEvent",
    "LiveEventKind",
    "Order",
    "OrderLine",
    "OrderStatus",
    "OrderStore",
    "StatusChange",
    "StatusListener",
    "StockLevel",
    "UnknownOrder",
    "UnknownSku",
    "ValidationError",
    "lines_from_payload",
    "merge_lines",
]
