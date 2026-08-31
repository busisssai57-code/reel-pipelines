"""Capture, fulfillment triggers, and the live-event boundary."""

import unittest

from fulfillment.errors import (
    InsufficientStock,
    InvalidTransition,
    UnknownOrder,
    ValidationError,
)
from fulfillment.inventory import InventoryStore
from fulfillment.models import OrderLine, OrderStatus
from fulfillment.service import (
    FulfillmentService,
    LiveEvent,
    LiveEventKind,
    lines_from_payload,
)


def service(**stock):
    return FulfillmentService(InventoryStore(stock or {"tee": 10}))


def placed(session_id="live-1", ref=None, **payload):
    payload.setdefault("sku", "tee")
    payload.setdefault("quantity", 1)
    return LiveEvent(
        kind=LiveEventKind.ORDER_PLACED,
        session_id=session_id,
        payload=payload,
        external_ref=ref,
    )


class Capture(unittest.TestCase):
    def test_capture_reserves_and_stores(self):
        svc = service(tee=10)
        order = svc.capture("live-1", [OrderLine("tee", 3, 500)])
        self.assertEqual(order.status, OrderStatus.RESERVED)
        self.assertEqual(svc.inventory.available("tee"), 7)
        self.assertIs(svc.orders.get(order.id), order)

    def test_capture_without_reserving_holds_no_stock(self):
        svc = service(tee=10)
        order = svc.capture("live-1", [OrderLine("tee", 3)], reserve=False)
        self.assertEqual(order.status, OrderStatus.CAPTURED)
        self.assertEqual(svc.inventory.available("tee"), 10)

    def test_failed_capture_stores_no_order_and_holds_no_stock(self):
        svc = service(tee=1)
        with self.assertRaises(InsufficientStock):
            svc.capture("live-1", [OrderLine("tee", 5)])
        self.assertEqual(len(svc.orders), 0)
        self.assertEqual(svc.inventory.available("tee"), 1)

    def test_capture_is_idempotent_on_external_ref(self):
        svc = service(tee=10)
        first = svc.capture("live-1", [OrderLine("tee", 2)], external_ref="c-1")
        second = svc.capture("live-1", [OrderLine("tee", 2)], external_ref="c-1")
        self.assertIs(first, second)
        # Critically, the replay must not reserve a second time.
        self.assertEqual(svc.inventory.available("tee"), 8)
        self.assertEqual(len(svc.orders), 1)


class Lifecycle(unittest.TestCase):
    def test_fulfill_depletes_stock(self):
        svc = service(tee=10)
        order = svc.capture("live-1", [OrderLine("tee", 4)])
        svc.fulfill(order.id)
        level = svc.inventory.level("tee")
        self.assertEqual(order.status, OrderStatus.FULFILLED)
        self.assertEqual((level.on_hand, level.reserved), (6, 0))

    def test_cancel_returns_stock(self):
        svc = service(tee=10)
        order = svc.capture("live-1", [OrderLine("tee", 4)])
        svc.cancel(order.id, "buyer changed mind")
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertEqual(svc.inventory.available("tee"), 10)
        self.assertEqual(svc.inventory.level("tee").on_hand, 10)

    def test_cancelling_after_fulfilment_is_rejected_and_changes_nothing(self):
        svc = service(tee=10)
        order = svc.capture("live-1", [OrderLine("tee", 4)])
        svc.fulfill(order.id)
        with self.assertRaises(InvalidTransition):
            svc.cancel(order.id)
        self.assertEqual(order.status, OrderStatus.FULFILLED)
        self.assertEqual(svc.inventory.level("tee").on_hand, 6)

    def test_double_fulfil_is_rejected_without_double_depleting(self):
        svc = service(tee=10)
        order = svc.capture("live-1", [OrderLine("tee", 4)])
        svc.fulfill(order.id)
        with self.assertRaises(InvalidTransition):
            svc.fulfill(order.id)
        self.assertEqual(svc.inventory.level("tee").on_hand, 6)

    def test_mark_failed_releases_hold(self):
        svc = service(tee=10)
        order = svc.capture("live-1", [OrderLine("tee", 4)])
        svc.mark_failed(order.id, "payment declined")
        self.assertEqual(order.status, OrderStatus.FAILED)
        self.assertEqual(svc.inventory.available("tee"), 10)

    def test_unknown_order_raises(self):
        svc = service()
        with self.assertRaises(UnknownOrder):
            svc.fulfill("ord_missing")


class Listeners(unittest.TestCase):
    def test_subscribers_see_every_transition(self):
        svc = service(tee=10)
        seen = []
        svc.subscribe(lambda order, change: seen.append(change.to_status))
        order = svc.capture("live-1", [OrderLine("tee", 1)])
        svc.fulfill(order.id)
        self.assertEqual(seen, [OrderStatus.RESERVED, OrderStatus.FULFILLED])

    def test_unsubscribe_stops_delivery(self):
        svc = service(tee=10)
        seen = []
        off = svc.subscribe(lambda o, c: seen.append(c))
        svc.capture("live-1", [OrderLine("tee", 1)])
        off()
        svc.capture("live-1", [OrderLine("tee", 1)])
        self.assertEqual(len(seen), 1)

    def test_a_raising_subscriber_cannot_break_an_order(self):
        svc = service(tee=10)
        good = []

        def explode(order, change):
            raise RuntimeError("overlay is down")

        svc.subscribe(explode)
        svc.subscribe(lambda o, c: good.append(c))
        order = svc.capture("live-1", [OrderLine("tee", 1)])
        self.assertEqual(order.status, OrderStatus.RESERVED)
        self.assertEqual(len(good), 1)


class PayloadParsing(unittest.TestCase):
    def test_accepts_single_sku_shape(self):
        lines = lines_from_payload({"sku": "tee", "quantity": 2, "unit_price_cents": 900})
        self.assertEqual(lines[0].sku, "tee")
        self.assertEqual(lines[0].quantity, 2)
        self.assertEqual(lines[0].unit_price_cents, 900)

    def test_accepts_lines_shape_and_defaults_quantity_to_one(self):
        lines = lines_from_payload({"lines": [{"sku": "a"}, {"sku": "b", "quantity": 3}]})
        self.assertEqual([(l.sku, l.quantity) for l in lines], [("a", 1), ("b", 3)])

    def test_rejects_unusable_payloads(self):
        for bad in ({}, {"lines": []}, {"lines": "tee"}, {"lines": [{"quantity": 1}]}):
            with self.subTest(payload=bad), self.assertRaises(ValidationError):
                lines_from_payload(bad)


class LiveEventBoundary(unittest.TestCase):
    def test_order_placed_reserves(self):
        svc = service(tee=10)
        result = svc.handle_live_event(placed(quantity=2, buyer_handle="@v"))
        self.assertTrue(result.ok)
        self.assertEqual(result.order.buyer_handle, "@v")
        self.assertEqual(svc.inventory.available("tee"), 8)

    def test_replayed_event_is_flagged_duplicate_and_reserves_once(self):
        svc = service(tee=10)
        first = svc.handle_live_event(placed(quantity=2, ref="comment-1"))
        again = svc.handle_live_event(placed(quantity=2, ref="comment-1"))
        self.assertFalse(first.duplicate)
        self.assertTrue(again.duplicate)
        self.assertEqual(again.order.id, first.order.id)
        self.assertEqual(svc.inventory.available("tee"), 8)

    def test_out_of_stock_returns_error_instead_of_raising(self):
        svc = service(tee=1)
        result = svc.handle_live_event(placed(quantity=5))
        self.assertFalse(result.ok)
        self.assertIsNone(result.order)
        self.assertEqual(result.detail["error_type"], "InsufficientStock")
        self.assertEqual(svc.inventory.available("tee"), 1)

    def test_unknown_sku_returns_error_instead_of_raising(self):
        svc = service(tee=5)
        result = svc.handle_live_event(placed(sku="ghost"))
        self.assertFalse(result.ok)
        self.assertEqual(result.detail["error_type"], "UnknownSku")

    def test_malformed_payload_returns_error_instead_of_raising(self):
        svc = service(tee=5)
        result = svc.handle_live_event(
            LiveEvent(kind=LiveEventKind.ORDER_PLACED, session_id="live-1", payload={})
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.detail["error_type"], "ValidationError")

    def test_cancel_event_by_order_id_and_by_ref(self):
        svc = service(tee=10)
        by_id = svc.handle_live_event(placed(quantity=1)).order
        result = svc.handle_live_event(
            LiveEvent(
                kind=LiveEventKind.ORDER_CANCELLED,
                session_id="live-1",
                payload={"order_id": by_id.id},
            )
        )
        self.assertTrue(result.ok)
        self.assertEqual(by_id.status, OrderStatus.CANCELLED)

        by_ref = svc.handle_live_event(placed(quantity=1, ref="c-9")).order
        result = svc.handle_live_event(
            LiveEvent(
                kind=LiveEventKind.ORDER_CANCELLED,
                session_id="live-1",
                payload={},
                external_ref="c-9",
            )
        )
        self.assertTrue(result.ok, result.error)
        self.assertEqual(by_ref.status, OrderStatus.CANCELLED)
        self.assertEqual(svc.inventory.available("tee"), 10)

    def test_cancel_event_without_any_identifier_errors(self):
        svc = service(tee=10)
        result = svc.handle_live_event(
            LiveEvent(
                kind=LiveEventKind.ORDER_CANCELLED, session_id="live-1", payload={}
            )
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.detail["error_type"], "ValidationError")

    def test_stock_sync_event_reports_drift(self):
        svc = service(tee=5)
        result = svc.handle_live_event(
            LiveEvent(
                kind=LiveEventKind.STOCK_SYNC,
                session_id="live-1",
                payload={"levels": {"tee": 12, "hat": 4}},
            )
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.detail["drift"], {"tee": 7, "hat": 4})
        self.assertEqual(svc.inventory.available("tee"), 12)

    def test_session_ended_summarises_without_touching_orders(self):
        svc = service(tee=10)
        kept = svc.handle_live_event(placed(quantity=2)).order
        result = svc.handle_live_event(
            LiveEvent(kind=LiveEventKind.SESSION_ENDED, session_id="live-1")
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.detail["open_orders"], 1)
        # Ending a broadcast must not silently drop a buyer's hold.
        self.assertEqual(kept.status, OrderStatus.RESERVED)
        self.assertEqual(svc.inventory.available("tee"), 8)


class SessionReporting(unittest.TestCase):
    def test_summary_counts_only_realised_revenue(self):
        svc = service(tee=10)
        done = svc.capture("live-1", [OrderLine("tee", 2, 1500)])
        svc.fulfill(done.id)
        svc.capture("live-1", [OrderLine("tee", 1, 1500)])  # still reserved
        svc.capture("live-2", [OrderLine("tee", 1, 1500)])  # other session

        summary = svc.session_summary("live-1")
        self.assertEqual(summary["orders"], 2)
        self.assertEqual(summary["units_fulfilled"], 2)
        self.assertEqual(summary["revenue_cents"], 3000)
        self.assertEqual(summary["open_orders"], 1)
        self.assertEqual(summary["by_status"], {"fulfilled": 1, "reserved": 1})

    def test_release_open_holds_frees_stock_for_that_session_only(self):
        svc = service(tee=10)
        svc.capture("live-1", [OrderLine("tee", 3)])
        other = svc.capture("live-2", [OrderLine("tee", 2)])
        cancelled = svc.release_open_holds("live-1")
        self.assertEqual(len(cancelled), 1)
        self.assertEqual(other.status, OrderStatus.RESERVED)
        self.assertEqual(svc.inventory.available("tee"), 8)


if __name__ == "__main__":
    unittest.main()
