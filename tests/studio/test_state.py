"""Derived state: activity folding, display names, and alerts."""

import unittest

from fulfillment import FulfillmentService, InventoryStore, OrderLine, OrderStatus
from studio.state import StudioState, describe_lines


def build(stock=None, names=None, **kw):
    service = FulfillmentService(InventoryStore(stock or {"tee": 10}))
    state = StudioState(service, session_id="live-1", names=names, **kw)
    state.attach()
    return service, state


class Describe(unittest.TestCase):
    def test_uses_display_name_and_omits_quantity_of_one(self):
        service, state = build(names={"tee": "Black Tee"})
        order = service.capture("live-1", [OrderLine("tee", 1, 100)])
        self.assertEqual(describe_lines(order, state.names), "Black Tee")

    def test_falls_back_to_sku_when_unnamed(self):
        service, state = build()
        order = service.capture("live-1", [OrderLine("tee", 2, 100)])
        self.assertEqual(describe_lines(order, state.names), "2x tee")

    def test_joins_multiple_lines(self):
        service, state = build(stock={"a": 5, "b": 5}, names={"a": "Alpha"})
        order = service.capture("live-1", [OrderLine("a", 2, 100), OrderLine("b", 1, 50)])
        self.assertEqual(describe_lines(order, state.names), "2x Alpha, b")


class Attachment(unittest.TestCase):
    def test_attach_is_idempotent(self):
        service, state = build()
        state.attach()
        service.capture("live-1", [OrderLine("tee", 1)])
        # One subscription, so one entry per change — not two.
        self.assertEqual(len(state.activity()), 1)

    def test_detach_stops_recording(self):
        service, state = build()
        state.detach()
        self.assertFalse(state.attached)
        service.capture("live-1", [OrderLine("tee", 1)])
        self.assertEqual(state.activity(), [])


class Activity(unittest.TestCase):
    def test_records_newest_first_with_transition(self):
        service, state = build(names={"tee": "Black Tee"})
        order = service.capture("live-1", [OrderLine("tee", 2, 500)], buyer_handle="@v")
        service.fulfill(order.id, "shipped")
        feed = state.activity()
        self.assertEqual([e["to_status"] for e in feed], ["fulfilled", "reserved"])
        self.assertEqual(feed[0]["buyer_handle"], "@v")
        self.assertEqual(feed[0]["summary"], "2x Black Tee")
        self.assertEqual(feed[0]["from_status"], "reserved")
        self.assertEqual(feed[0]["reason"], "shipped")

    def test_ring_buffer_discards_oldest(self):
        service, state = build(stock={"tee": 500}, activity_limit=5)
        for _ in range(8):
            service.capture("live-1", [OrderLine("tee", 1)])
        self.assertEqual(len(state.activity(limit=100)), 5)

    def test_transition_counts_count_entries_not_current_state(self):
        service, state = build()
        order = service.capture("live-1", [OrderLine("tee", 1)])
        service.fulfill(order.id)
        service.capture("live-1", [OrderLine("tee", 1)])
        self.assertEqual(state.transition_counts(), {"reserved": 2, "fulfilled": 1})


class OrderRows(unittest.TestCase):
    def test_offers_only_legal_actions(self):
        service, state = build()
        order = service.capture("live-1", [OrderLine("tee", 1)])
        reserved = state.order_rows()[0]
        self.assertEqual(
            sorted(reserved["actions"]), ["cancelled", "failed", "fulfilled"]
        )
        service.fulfill(order.id)
        self.assertEqual(state.order_rows()[0]["actions"], [])

    def test_scopes_to_the_current_session(self):
        service, state = build()
        service.capture("live-1", [OrderLine("tee", 1)])
        service.capture("live-2", [OrderLine("tee", 1)])
        self.assertEqual(len(state.order_rows()), 1)
        self.assertEqual(len(state.order_rows(session_only=False)), 2)

    def test_set_session_reroutes_the_view(self):
        service, state = build()
        service.capture("live-2", [OrderLine("tee", 1)])
        self.assertEqual(state.order_rows(), [])
        state.set_session("live-2")
        self.assertEqual(len(state.order_rows()), 1)

    def test_newest_order_first(self):
        service, state = build()
        first = service.capture("live-1", [OrderLine("tee", 1)])
        second = service.capture("live-1", [OrderLine("tee", 1)])
        self.assertEqual(
            [r["id"] for r in state.order_rows()], [second.id, first.id]
        )


class Alerts(unittest.TestCase):
    def test_warns_when_stock_is_fully_reserved(self):
        service, state = build(stock={"tee": 2}, names={"tee": "Black Tee"})
        service.capture("live-1", [OrderLine("tee", 2)])
        texts = [a["text"] for a in state.alerts()]
        self.assertTrue(any("No units available: Black Tee" in t for t in texts))

    def test_reports_empty_stock_separately_from_reserved(self):
        service, state = build(stock={"tee": 0}, names={"tee": "Black Tee"})
        levels = {a["level"] for a in state.alerts()}
        texts = " ".join(a["text"] for a in state.alerts())
        self.assertIn("Out of stock: Black Tee", texts)
        # on_hand 0 is not the same condition as sold-out-by-reservation.
        self.assertNotIn("No units available", texts)
        self.assertIn("info", levels)

    def test_warns_when_not_attached(self):
        service, state = build()
        state.detach()
        self.assertTrue(any("Not subscribed" in a["text"] for a in state.alerts()))

    def test_quiet_when_healthy(self):
        service, state = build(stock={"tee": 5})
        self.assertEqual(state.alerts(), [])


class Snapshot(unittest.TestCase):
    def test_contains_every_section(self):
        service, state = build(names={"tee": "Black Tee"})
        order = service.capture("live-1", [OrderLine("tee", 2, 1500)], buyer_handle="@v")
        service.fulfill(order.id)
        snap = state.snapshot()
        for key in (
            "generated_at", "session_id", "attached", "summary", "transitions",
            "orders", "inventory", "activity", "alerts", "uptime_seconds",
        ):
            self.assertIn(key, snap)
        self.assertEqual(snap["summary"]["revenue_cents"], 3000)
        self.assertEqual(snap["inventory"][0]["on_hand"], 8)

    def test_a_broken_record_call_cannot_raise(self):
        service, state = build()
        order = service.capture("live-1", [OrderLine("tee", 1)])
        # A malformed change object must be swallowed, not propagated into
        # the service's subscriber loop.
        state.record(order, object())
        self.assertEqual(len(state.activity()), 1)


if __name__ == "__main__":
    unittest.main()
