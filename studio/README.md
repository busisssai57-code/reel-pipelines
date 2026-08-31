# Automation Studio

The operator dashboard: monitor orders and stock during a broadcast, and act on
them. Pure standard library, Python 3.11+, no build step.

```bash
python3 -m studio --demo          # preview with sample data
python3 -m pytest tests/studio -q # 62 tests
```

## Wiring it to a live stream

The order and inventory stores live in memory inside the streamer process, so a
separate process cannot see a running broadcast. Launch it **in-process**:

```python
from studio import launch

studio = launch(pipeline.commerce, names=cfg.commerce.sku_names)
log.info("Studio at %s", studio.url)
...
studio.stop()
```

`launch` accepts a `CommerceBridge` (reaching through its public `.service`) or
a bare `FulfillmentService`, and picks up `session_id` from the bridge so the
view scopes to the broadcast already running. This package imports nothing from
`bta` — the same one-way rule the fulfillment module follows.

It subscribes once and folds each status change into an activity log, rather
than polling the order store. `python -m studio` standalone is for looking at
the interface; it always serves demo data and says so.

## Security

**Binds to `127.0.0.1` by default.** The control endpoints fulfil and cancel
real orders and have no authentication, so a wider bind puts order control on
the network — `serve()` warns when asked to do that. Use `--read-only` (which
serves the view and refuses every mutation with 403) or tunnel to loopback.

Buyer handles and order reasons come from live chat, so they are hostile input.
The page renders every value with `textContent` and builds no markup from data;
a viewer named `<img src=x onerror=...>` reaches the operator's browser as
inert text. There is a test asserting the page contains no `innerHTML`. The
page also loads nothing from the network, so the studio starts on a machine
that is offline mid-broadcast.

## API

| Method | Path | Effect |
|---|---|---|
| `GET` | `/` | The dashboard |
| `GET` | `/api/snapshot` | Everything the page renders, in one read |
| `GET` | `/api/orders`, `/api/inventory`, `/api/activity` | Individual sections |
| `GET` | `/api/health` | Liveness, attachment, uptime |
| `POST` | `/api/orders/{id}/fulfill\|cancel\|fail` | Transition an order |
| `POST` | `/api/inventory/restock` | `{sku, quantity}` — known SKUs only |
| `POST` | `/api/inventory/sync` | `{levels: {sku: count}}` — returns drift |
| `POST` | `/api/session` | `{session_id}` — repoint the view |

Status codes distinguish caller error from state conflict: `400` malformed,
`404` unknown order or SKU, **`409` well-formed but conflicting** (already
fulfilled, sold out), `403` read-only, `413` oversized body. A sold-out SKU is
not the caller's mistake, so it is not a `400`.

Restock refuses an unknown SKU rather than registering it — a typo should not
be able to invent a product. Adding products is a catalog change.

The `actions` list on each order row comes from the state machine
(`Order.can_transition_to`), so the page can never offer an illegal control.

## Layout

| File | Owns |
|---|---|
| `state.py` | `StudioState` — subscription, activity ring buffer, derived rows, alerts |
| `api.py` | `StudioAPI` — routing as a pure function of (method, path, body) |
| `server.py` | `StudioServer` — HTTP transport, bind warnings, body limits |
| `ui.py` | The page: one inlined HTML document |
| `__main__.py` | `python -m studio`, demo data |

Routing is deliberately separate from transport: the whole API is tested
without opening a socket, and `server.py` stays a thin adapter.

## Not built

**Scheduling go-lives.** The README lists scheduling alongside monitoring, and
it is not here. Starting a broadcast on a timer needs a lifecycle hook on the
streamer side to call, and none is exposed today — a scheduler with nothing to
drive would be a UI over a stub. It wants `bta` to expose start/stop for a
broadcast first.
