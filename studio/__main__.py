"""``python -m studio`` — run the dashboard on its own.

The order and inventory stores live in memory inside the streamer process, so
a separate process cannot observe a running broadcast. This entrypoint is for
looking at the interface and exercising the API; to monitor a real stream, call
:func:`studio.launch` from inside the pipeline.
"""

from __future__ import annotations

import argparse
import sys

from fulfillment import FulfillmentService, InventoryStore, OrderLine

from . import DEFAULT_HOST, DEFAULT_PORT, StudioState, serve

DEMO_PRODUCTS = {
    "tee-blk-l": ("Black Tee (L)", 12, 2500),
    "tee-blk-m": ("Black Tee (M)", 4, 2500),
    "hoodie-gry-l": ("Grey Hoodie (L)", 0, 5500),
    "sticker-pack": ("Sticker Pack", 60, 800),
}


def build_demo() -> StudioState:
    """A service seeded with products and a few orders in mixed states."""
    stock = {sku: qty for sku, (_, qty, _) in DEMO_PRODUCTS.items()}
    names = {sku: name for sku, (name, _, _) in DEMO_PRODUCTS.items()}
    prices = {sku: cents for sku, (_, _, cents) in DEMO_PRODUCTS.items()}

    service = FulfillmentService(InventoryStore(stock))
    state = StudioState(service, session_id="demo-session", names=names)
    state.attach()

    def order(sku: str, qty: int, buyer: str):
        return service.capture(
            "demo-session",
            [OrderLine(sku, qty, prices[sku])],
            buyer_handle=buyer,
            external_ref=f"demo-{buyer}-{sku}",
        )

    shipped = order("tee-blk-l", 1, "@earlybird")
    service.fulfill(shipped.id, "shipped")
    order("sticker-pack", 3, "@collector")
    order("tee-blk-m", 2, "@viewer_two")
    dropped = order("sticker-pack", 1, "@mistake")
    service.cancel(dropped.id, "buyer changed their mind")
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m studio", description=__doc__.splitlines()[0]
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="bind address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="bind port")
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="serve the view without the fulfil, cancel, and restock controls",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="seed sample products and orders (the default when run standalone)",
    )
    args = parser.parse_args(argv)

    state = build_demo()
    if not args.demo:
        print(
            "Running with demo data: a separate process cannot see a live "
            "broadcast's in-memory orders. Call studio.launch() from the "
            "pipeline to monitor a real stream.",
            file=sys.stderr,
        )

    server = serve(
        state, host=args.host, port=args.port, read_only=args.read_only
    )
    print(f"Studio: {server.url}")
    try:
        server.wait()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
