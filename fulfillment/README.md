# Product Fulfillment

Order capture, inventory sync, and fulfillment triggers tied to live session
activity. Pure standard library, Python 3.11+.

```bash
python3 -m pytest tests/fulfillment -q   # 58 tests
```

Tests are plain `unittest.TestCase` classes (no framework dependency in the
test bodies) collected by the project's pytest. `tests/` is intentionally not
a package — sibling suites import their fixtures as top-level `conftest`, which
only resolves while pytest keeps `tests/` on `sys.path`.

## Integration contract for the streamer

**This package imports nothing from the streaming side.** It defines its own
`LiveEvent` type; the streamer adapts its events to that shape at the boundary.
Neither module needs to know the other's internals, and both stay testable
alone.

```python
from fulfillment import FulfillmentService, InventoryStore, LiveEvent, LiveEventKind

service = FulfillmentService(InventoryStore({"tee-blk-l": 40}))

result = service.handle_live_event(LiveEvent(
    kind=LiveEventKind.ORDER_PLACED,
    session_id="live-2026-08-31",
    payload={"sku": "tee-blk-l", "quantity": 2, "buyer_handle": "@viewer"},
    external_ref="comment-8823",
))
if result.ok:
    service.fulfill(result.order.id)
else:
    log.warning("order rejected: %s", result.error)
```

### Three things worth knowing before you wire it up

**1. `handle_live_event` never raises.** It is the resilience boundary: an
out-of-stock buyer, an unknown SKU, or a malformed payload must not be able to
take the broadcast down. Every failure comes back as `EventResult(ok=False)`
with `error` set and `detail["error_type"]` naming the exception class. Check
`result.ok`; do not wrap it in a try/except and assume silence means success.

The direct methods — `capture`, `fulfill`, `cancel`, `mark_failed` — *do*
raise. Use those where you can handle an exception.

**2. `external_ref` is the idempotency key, and you should always set it.**
Live comment streams redeliver. Pass the originating comment/checkout id and a
replay returns the original order with `result.duplicate == True`, reserving
nothing a second time. Without a ref, a redelivered event creates a second
order and holds stock twice.

**3. Stock is two-phase.** `available = on_hand - reserved`. Capture *reserves*;
`fulfill()` converts that hold into a real depletion. Reservations across
several SKUs are all-or-nothing, so a basket that cannot be filled completely
holds nothing at all. This is what stops a 50-unit drop overselling to 200
simultaneous buyers — there is a test for exactly that.

### Events accepted

| Kind | Payload | Effect |
|---|---|---|
| `ORDER_PLACED` | `{sku, quantity, unit_price_cents, buyer_handle}` or `{lines: [...]}` | Captures and reserves |
| `ORDER_CANCELLED` | `{order_id, reason}`, or an `external_ref` seen before | Cancels, releases hold |
| `STOCK_SYNC` | `{levels: {sku: count}}` | Reconciles on-hand, returns drift |
| `SESSION_ENDED` | — | Returns a summary; **changes nothing** |

`SESSION_ENDED` is deliberately non-destructive: dropping a buyer's held stock
because a broadcast ended is a policy decision, not a default. Call
`service.release_open_holds(session_id)` explicitly if that is the behaviour
you want.

`STOCK_SYNC` refuses to set on-hand below units already reserved — those are
promised to live buyers, and honouring the sync would oversell after the fact.

### Reading state without polling

```python
unsubscribe = service.subscribe(lambda order, change: overlay.push(order))
```

Fires on every committed status change. A subscriber that raises is isolated —
it cannot break order processing. This is the seam for stream overlays and the
dashboard; neither should poll the order store.

`service.session_summary(session_id)` returns order counts by status, units
fulfilled, realised revenue, and open orders. Revenue counts **fulfilled orders
only**, never reserved ones.

## Order lifecycle

```
CAPTURED ──reserve──> RESERVED ──commit──> FULFILLED
    │                     │
    └──> CANCELLED        ├──> CANCELLED     (a decision: buyer/operator pulled it)
    └──> FAILED           └──> FAILED        (a system outcome: payment declined)
```

`CANCELLED` and `FAILED` are both terminal and both release stock, but they are
not interchangeable — reporting needs to tell a pulled order from a lost sale.
Illegal transitions raise `InvalidTransition` and leave the order untouched.
Every order carries a `history` audit trail of timestamped changes.

## Storage

`InventoryStore` and `OrderStore` are in-memory and thread-safe. They are the
reference implementations of the interface a durable backend (Postgres, Redis,
a supplier API) is expected to satisfy. Depend on the method surface, not on
the fact that they are dicts today. Both are injectable:

```python
FulfillmentService(inventory=MyPostgresInventory(), orders=MyPostgresOrders())
```

## Layout

| File | Owns |
|---|---|
| `models.py` | `OrderLine`, `Order`, `OrderStatus`, the transition table |
| `inventory.py` | `InventoryStore` — reserve / release / commit / sync |
| `orders.py` | `OrderStore` — id and `external_ref` indexes |
| `service.py` | `FulfillmentService`, `LiveEvent`, `EventResult` |
| `errors.py` | Exception hierarchy, all under `FulfillmentError` |
