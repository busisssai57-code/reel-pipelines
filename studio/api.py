"""JSON API routing, independent of the HTTP transport.

Routing is a pure function of (method, path, body), which keeps the whole API
testable without opening a socket. :mod:`studio.server` is the thin adapter
that turns real requests into these calls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from fulfillment.errors import (
    FulfillmentError,
    InsufficientStock,
    InvalidTransition,
    UnknownOrder,
    UnknownSku,
    ValidationError,
)

from .state import StudioState, describe_lines

#: Fulfillment errors mapped onto the status code that describes them. 409
#: marks a request that was well-formed but conflicts with current state — a
#: sold-out SKU or an already-fulfilled order is not the caller's mistake.
ERROR_STATUS: Mapping[type, int] = {
    ValidationError: 400,
    UnknownOrder: 404,
    UnknownSku: 404,
    InsufficientStock: 409,
    InvalidTransition: 409,
}


@dataclass(frozen=True, slots=True)
class ApiResponse:
    status: int
    body: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def encode(self) -> bytes:
        return json.dumps(self.body, default=str).encode("utf-8")


def _error(status: int, message: str, **extra: Any) -> ApiResponse:
    return ApiResponse(status, {"error": message, **extra})


def _status_for(exc: FulfillmentError) -> int:
    for kind, status in ERROR_STATUS.items():
        if isinstance(exc, kind):
            return status
    return 400


class StudioAPI:
    """Read and control endpoints over one :class:`StudioState`."""

    #: Order transitions the API exposes, mapped to the service method.
    TRANSITIONS = {
        "fulfill": "fulfill",
        "cancel": "cancel",
        "fail": "mark_failed",
    }

    def __init__(self, state: StudioState, *, read_only: bool = False) -> None:
        self.state = state
        self.read_only = read_only

    @property
    def service(self):
        return self.state.service

    def handle(self, method: str, path: str, body: bytes = b"") -> ApiResponse:
        """Route one request. Never raises; every failure becomes a response."""
        try:
            return self._route(method.upper(), path.rstrip("/") or "/", body)
        except FulfillmentError as exc:
            return _error(_status_for(exc), str(exc), error_type=type(exc).__name__)
        except Exception as exc:  # noqa: BLE001 - the dashboard must stay up
            return _error(500, f"unexpected error: {exc}", error_type=type(exc).__name__)

    # -- routing ---------------------------------------------------------

    def _route(self, method: str, path: str, body: bytes) -> ApiResponse:
        segments = [s for s in path.split("/") if s]
        if not segments or segments[0] != "api":
            return _error(404, f"no such endpoint: {path}")
        rest = segments[1:]

        if method == "GET":
            return self._get(rest)
        if method == "POST":
            if self.read_only:
                return _error(403, "studio is running in read-only mode")
            return self._post(rest, body)
        return _error(405, f"method not allowed: {method}")

    def _get(self, rest: list[str]) -> ApiResponse:
        match rest:
            case ["snapshot"]:
                return ApiResponse(200, {**self.state.snapshot(), "read_only": self.read_only})
            case ["orders"]:
                return ApiResponse(200, {"orders": self.state.order_rows()})
            case ["inventory"]:
                return ApiResponse(200, {"inventory": self.state.inventory_rows()})
            case ["activity"]:
                return ApiResponse(200, {"activity": self.state.activity()})
            case ["health"]:
                return ApiResponse(
                    200,
                    {
                        "ok": True,
                        "attached": self.state.attached,
                        "session_id": self.state.session_id,
                        "uptime_seconds": round(self.state.uptime_seconds(), 1),
                    },
                )
        return _error(404, "no such endpoint: /" + "/".join(["api", *rest]))

    def _post(self, rest: list[str], body: bytes) -> ApiResponse:
        match rest:
            case ["orders", order_id, action] if action in self.TRANSITIONS:
                return self._transition(order_id, action, body)
            case ["inventory", "restock"]:
                return self._restock(body)
            case ["inventory", "sync"]:
                return self._sync(body)
            case ["session"]:
                payload = self._payload(body)
                session_id = str(payload.get("session_id", "")).strip()
                if not session_id:
                    return _error(400, "session_id is required")
                self.state.set_session(session_id)
                return ApiResponse(200, {"session_id": self.state.session_id})
        return _error(404, "no such endpoint: /" + "/".join(["api", *rest]))

    def _transition(self, order_id: str, action: str, body: bytes) -> ApiResponse:
        payload = self._payload(body)
        reason = str(payload.get("reason") or f"{action} from studio")
        method = getattr(self.service, self.TRANSITIONS[action])
        order = method(order_id, reason)
        return ApiResponse(
            200, {"order": self._order_view(order), "action": action}
        )

    def _restock(self, body: bytes) -> ApiResponse:
        payload = self._payload(body)
        sku = str(payload.get("sku", "")).strip()
        if not sku:
            return _error(400, "sku is required")
        try:
            quantity = int(payload.get("quantity", 0))
        except (TypeError, ValueError):
            return _error(400, "quantity must be an integer")
        if quantity <= 0:
            return _error(400, "quantity must be positive")
        if not self.service.inventory.knows(sku):
            # Registering here would let a typo invent a product, so require
            # the SKU to exist. Adding products is a catalog change, not a
            # restock.
            return _error(404, f"unknown sku: {sku}")
        on_hand = self.service.inventory.restock(sku, quantity)
        return ApiResponse(200, {"sku": sku, "on_hand": on_hand})

    def _sync(self, body: bytes) -> ApiResponse:
        payload = self._payload(body)
        levels = payload.get("levels")
        if not isinstance(levels, Mapping) or not levels:
            return _error(400, "levels must be a non-empty object of sku -> count")
        try:
            parsed = {str(k): int(v) for k, v in levels.items()}
        except (TypeError, ValueError):
            return _error(400, "every level count must be an integer")
        drift = self.service.inventory.sync(parsed)
        return ApiResponse(200, {"drift": drift})

    # -- helpers ---------------------------------------------------------

    def _payload(self, body: bytes) -> dict[str, Any]:
        if not body:
            return {}
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError(f"body is not valid JSON: {exc}") from None
        if not isinstance(parsed, dict):
            raise ValidationError("body must be a JSON object")
        return parsed

    def _order_view(self, order) -> dict[str, Any]:
        return {
            "id": order.id,
            "status": order.status.value,
            "buyer_handle": order.buyer_handle,
            "summary": describe_lines(order, self.state.names),
            "total_cents": order.total_cents,
        }
