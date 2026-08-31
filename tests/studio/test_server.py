"""HTTP transport: real requests against a real socket."""

import json
import unittest
import urllib.error
import urllib.request

from fulfillment import FulfillmentService, InventoryStore, OrderLine
from studio.server import MAX_BODY_BYTES, StudioServer, is_loopback, serve
from studio.state import StudioState
from studio.ui import PAGE


def get(url, method="GET", payload=None):
    """Return (status, body) without raising on 4xx/5xx."""
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


class ServerTestCase(unittest.TestCase):
    stock = {"tee": 10}
    read_only = False

    def setUp(self):
        self.service = FulfillmentService(InventoryStore(dict(self.stock)))
        self.state = StudioState(self.service, session_id="live-1", names={"tee": "Black Tee"})
        self.state.attach()
        self.server = StudioServer(
            self.state, port=0, read_only=self.read_only, on_log=lambda msg: None
        ).start()
        self.addCleanup(self.server.stop)
        self.url = self.server.url


class Serving(ServerTestCase):
    def test_serves_the_page_at_root(self):
        status, body, headers = get(self.url)
        self.assertEqual(status, 200)
        self.assertIn(b"Automation Studio", body)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))

    def test_security_headers_present(self):
        _, _, headers = get(self.url)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_snapshot_round_trips_as_json(self):
        self.service.capture("live-1", [OrderLine("tee", 2, 500)], buyer_handle="@v")
        status, body, headers = get(self.url + "api/snapshot")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["Content-Type"])
        snapshot = json.loads(body)
        self.assertEqual(len(snapshot["orders"]), 1)
        self.assertEqual(snapshot["orders"][0]["summary"], "2x Black Tee")

    def test_query_string_is_ignored(self):
        status, _, _ = get(self.url + "api/health?cache_bust=1")
        self.assertEqual(status, 200)

    def test_unknown_path_is_404_json(self):
        status, body, _ = get(self.url + "api/nothing")
        self.assertEqual(status, 404)
        self.assertIn("error", json.loads(body))

    def test_control_action_over_the_wire(self):
        order = self.service.capture("live-1", [OrderLine("tee", 3)])
        status, body, _ = get(
            f"{self.url}api/orders/{order.id}/fulfill", "POST", {"reason": "shipped"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["order"]["status"], "fulfilled")
        self.assertEqual(self.service.inventory.level("tee").on_hand, 7)

    def test_conflict_surfaces_as_409(self):
        order = self.service.capture("live-1", [OrderLine("tee", 1)])
        get(f"{self.url}api/orders/{order.id}/fulfill", "POST", {})
        status, _, _ = get(f"{self.url}api/orders/{order.id}/cancel", "POST", {})
        self.assertEqual(status, 409)

    def test_oversized_body_is_refused(self):
        request = urllib.request.Request(
            self.url + "api/inventory/sync",
            data=b"x" * (MAX_BODY_BYTES + 1),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request)
        self.assertEqual(ctx.exception.code, 413)

    def test_server_survives_a_bad_request(self):
        get(self.url + "api/inventory/sync", "POST", "not-an-object")
        status, _, _ = get(self.url + "api/health")
        self.assertEqual(status, 200)


class ReadOnlyServer(ServerTestCase):
    read_only = True

    def test_controls_refused_over_the_wire(self):
        order = self.service.capture("live-1", [OrderLine("tee", 1)])
        status, _, _ = get(f"{self.url}api/orders/{order.id}/fulfill", "POST", {})
        self.assertEqual(status, 403)
        self.assertEqual(order.status.value, "reserved")

    def test_page_and_reads_still_served(self):
        self.assertEqual(get(self.url)[0], 200)
        self.assertEqual(get(self.url + "api/snapshot")[0], 200)


class Lifecycle(unittest.TestCase):
    def test_context_manager_starts_and_stops(self):
        service = FulfillmentService(InventoryStore({"tee": 1}))
        state = StudioState(service)
        with StudioServer(state, port=0, on_log=lambda m: None) as server:
            url = server.url
            self.assertEqual(get(url + "api/health")[0], 200)
        with self.assertRaises(Exception):
            urllib.request.urlopen(url + "api/health", timeout=1)

    def test_start_is_idempotent(self):
        service = FulfillmentService(InventoryStore({"tee": 1}))
        server = StudioServer(StudioState(service), port=0, on_log=lambda m: None)
        self.addCleanup(server.stop)
        self.assertIs(server.start(), server.start())


class BindWarning(unittest.TestCase):
    def test_loopback_detection(self):
        for host in ("127.0.0.1", "localhost", "::1", ""):
            self.assertTrue(is_loopback(host), host)
        for host in ("0.0.0.0", "192.168.1.5", "example.com"):
            self.assertFalse(is_loopback(host), host)

    def test_public_bind_with_controls_warns(self):
        warnings = []
        service = FulfillmentService(InventoryStore({"tee": 1}))
        server = serve(
            StudioState(service), host="0.0.0.0", port=0,
            on_log=lambda m: None, warn=warnings.append,
        )
        self.addCleanup(server.stop)
        self.assertEqual(len(warnings), 1)
        self.assertIn("no authentication", warnings[0])

    def test_loopback_bind_is_quiet(self):
        warnings = []
        service = FulfillmentService(InventoryStore({"tee": 1}))
        server = serve(
            StudioState(service), port=0, on_log=lambda m: None, warn=warnings.append
        )
        self.addCleanup(server.stop)
        self.assertEqual(warnings, [])

    def test_read_only_public_bind_does_not_warn(self):
        warnings = []
        service = FulfillmentService(InventoryStore({"tee": 1}))
        server = serve(
            StudioState(service), host="0.0.0.0", port=0, read_only=True,
            on_log=lambda m: None, warn=warnings.append,
        )
        self.addCleanup(server.stop)
        self.assertEqual(warnings, [])


class PageSafety(unittest.TestCase):
    def test_page_never_builds_markup_from_data(self):
        # Buyer handles and reasons come from live chat, so a viewer named
        # "<img onerror=...>" must not be able to run script in the operator's
        # browser. Everything is written with textContent.
        self.assertNotIn("innerHTML", PAGE)
        self.assertNotIn("outerHTML", PAGE)
        self.assertNotIn("document.write", PAGE)

    def test_page_loads_nothing_from_the_network(self):
        # The studio has to start on a machine that may be offline mid-stream.
        self.assertNotIn("http://", PAGE)
        self.assertNotIn("https://", PAGE)
        self.assertNotIn("<script src", PAGE)


class HostileContent(ServerTestCase):
    def test_script_like_buyer_handle_is_served_as_data(self):
        payload = '<img src=x onerror="alert(1)">'
        self.service.capture(
            "live-1", [OrderLine("tee", 1)], buyer_handle=payload, external_ref="x"
        )
        _, body, _ = get(self.url + "api/snapshot")
        snapshot = json.loads(body)
        # It survives as an exact string in JSON — the page renders it through
        # textContent, so it is never parsed as markup.
        self.assertEqual(snapshot["orders"][0]["buyer_handle"], payload)


if __name__ == "__main__":
    unittest.main()
