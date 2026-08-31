"""API routing: status codes, control actions, and read-only mode."""

import json
import unittest

from fulfillment import FulfillmentService, InventoryStore, OrderLine
from studio.api import StudioAPI
from studio.state import StudioState


def build(stock=None, read_only=False):
    service = FulfillmentService(InventoryStore(stock or {"tee": 10}))
    state = StudioState(service, session_id="live-1", names={"tee": "Black Tee"})
    state.attach()
    return service, state, StudioAPI(state, read_only=read_only)


def body(payload):
    return json.dumps(payload).encode("utf-8")


class Reads(unittest.TestCase):
    def test_endpoints_return_their_section(self):
        service, _, api = build()
        service.capture("live-1", [OrderLine("tee", 1)])
        for path, key in (
            ("/api/orders", "orders"),
            ("/api/inventory", "inventory"),
            ("/api/activity", "activity"),
        ):
            with self.subTest(path=path):
                response = api.handle("GET", path)
                self.assertEqual(response.status, 200)
                self.assertIn(key, response.body)

    def test_snapshot_reports_read_only_flag(self):
        _, _, api = build(read_only=True)
        self.assertTrue(api.handle("GET", "/api/snapshot").body["read_only"])

    def test_health(self):
        _, _, api = build()
        health = api.handle("GET", "/api/health").body
        self.assertTrue(health["ok"])
        self.assertTrue(health["attached"])

    def test_trailing_slash_is_tolerated(self):
        _, _, api = build()
        self.assertEqual(api.handle("GET", "/api/orders/").status, 200)

    def test_unknown_paths_and_methods(self):
        _, _, api = build()
        self.assertEqual(api.handle("GET", "/api/nope").status, 404)
        self.assertEqual(api.handle("GET", "/nope").status, 404)
        self.assertEqual(api.handle("DELETE", "/api/orders").status, 405)


class Transitions(unittest.TestCase):
    def test_fulfill_cancel_and_fail(self):
        for action, expected in (
            ("fulfill", "fulfilled"),
            ("cancel", "cancelled"),
            ("fail", "failed"),
        ):
            with self.subTest(action=action):
                service, _, api = build()
                order = service.capture("live-1", [OrderLine("tee", 1)])
                response = api.handle("POST", f"/api/orders/{order.id}/{action}")
                self.assertEqual(response.status, 200)
                self.assertEqual(response.body["order"]["status"], expected)

    def test_custom_reason_is_recorded(self):
        service, _, api = build()
        order = service.capture("live-1", [OrderLine("tee", 1)])
        api.handle(
            "POST", f"/api/orders/{order.id}/cancel", body({"reason": "duplicate gift"})
        )
        self.assertEqual(order.history[-1].reason, "duplicate gift")

    def test_illegal_transition_is_409_not_500(self):
        service, _, api = build()
        order = service.capture("live-1", [OrderLine("tee", 1)])
        api.handle("POST", f"/api/orders/{order.id}/fulfill")
        response = api.handle("POST", f"/api/orders/{order.id}/cancel")
        self.assertEqual(response.status, 409)
        self.assertEqual(response.body["error_type"], "InvalidTransition")

    def test_unknown_order_is_404(self):
        _, _, api = build()
        response = api.handle("POST", "/api/orders/ord_nope/fulfill")
        self.assertEqual(response.status, 404)

    def test_unknown_action_is_404(self):
        service, _, api = build()
        order = service.capture("live-1", [OrderLine("tee", 1)])
        self.assertEqual(
            api.handle("POST", f"/api/orders/{order.id}/explode").status, 404
        )

    def test_fulfilling_depletes_stock_through_the_api(self):
        service, _, api = build(stock={"tee": 5})
        order = service.capture("live-1", [OrderLine("tee", 2)])
        api.handle("POST", f"/api/orders/{order.id}/fulfill")
        self.assertEqual(service.inventory.level("tee").on_hand, 3)


class InventoryControl(unittest.TestCase):
    def test_restock_adds_units(self):
        service, _, api = build(stock={"tee": 1})
        response = api.handle("POST", "/api/inventory/restock", body({"sku": "tee", "quantity": 9}))
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body["on_hand"], 10)

    def test_restock_rejects_unknown_sku_rather_than_inventing_one(self):
        service, _, api = build()
        response = api.handle(
            "POST", "/api/inventory/restock", body({"sku": "typo", "quantity": 5})
        )
        self.assertEqual(response.status, 404)
        self.assertFalse(service.inventory.knows("typo"))

    def test_restock_validates_quantity(self):
        _, _, api = build()
        for payload in ({"sku": "tee"}, {"sku": "tee", "quantity": 0},
                        {"sku": "tee", "quantity": -2}, {"sku": "tee", "quantity": "x"}):
            with self.subTest(payload=payload):
                self.assertEqual(
                    api.handle("POST", "/api/inventory/restock", body(payload)).status, 400
                )

    def test_restock_requires_a_sku(self):
        _, _, api = build()
        self.assertEqual(
            api.handle("POST", "/api/inventory/restock", body({"quantity": 3})).status, 400
        )

    def test_sync_reports_drift(self):
        _, _, api = build(stock={"tee": 5})
        response = api.handle("POST", "/api/inventory/sync", body({"levels": {"tee": 9}}))
        self.assertEqual(response.body["drift"], {"tee": 4})

    def test_sync_below_reserved_is_409(self):
        service, _, api = build(stock={"tee": 10})
        service.capture("live-1", [OrderLine("tee", 8)])
        response = api.handle("POST", "/api/inventory/sync", body({"levels": {"tee": 2}}))
        self.assertEqual(response.status, 400)
        self.assertEqual(service.inventory.level("tee").on_hand, 10)

    def test_sync_validates_shape(self):
        _, _, api = build()
        for payload in ({}, {"levels": {}}, {"levels": "tee"}, {"levels": {"tee": "x"}}):
            with self.subTest(payload=payload):
                self.assertEqual(
                    api.handle("POST", "/api/inventory/sync", body(payload)).status, 400
                )


class SessionControl(unittest.TestCase):
    def test_switching_session_changes_the_view(self):
        service, state, api = build()
        service.capture("live-2", [OrderLine("tee", 1)])
        self.assertEqual(api.handle("GET", "/api/orders").body["orders"], [])
        api.handle("POST", "/api/session", body({"session_id": "live-2"}))
        self.assertEqual(state.session_id, "live-2")
        self.assertEqual(len(api.handle("GET", "/api/orders").body["orders"]), 1)

    def test_blank_session_is_rejected(self):
        _, _, api = build()
        self.assertEqual(
            api.handle("POST", "/api/session", body({"session_id": "  "})).status, 400
        )


class Malformed(unittest.TestCase):
    def test_invalid_json_is_400(self):
        _, _, api = build()
        response = api.handle("POST", "/api/inventory/sync", b"{not json")
        self.assertEqual(response.status, 400)

    def test_non_object_body_is_400(self):
        _, _, api = build()
        self.assertEqual(
            api.handle("POST", "/api/inventory/sync", b"[1,2,3]").status, 400
        )

    def test_empty_body_is_treated_as_empty_object(self):
        service, _, api = build()
        order = service.capture("live-1", [OrderLine("tee", 1)])
        self.assertEqual(api.handle("POST", f"/api/orders/{order.id}/cancel", b"").status, 200)


class ReadOnly(unittest.TestCase):
    def test_reads_allowed_writes_refused(self):
        service, _, api = build(read_only=True)
        order = service.capture("live-1", [OrderLine("tee", 1)])
        self.assertEqual(api.handle("GET", "/api/snapshot").status, 200)
        for path in (
            f"/api/orders/{order.id}/fulfill",
            "/api/inventory/restock",
            "/api/session",
        ):
            with self.subTest(path=path):
                self.assertEqual(api.handle("POST", path, b"{}").status, 403)
        self.assertEqual(order.status.value, "reserved")


if __name__ == "__main__":
    unittest.main()
