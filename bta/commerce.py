"""Bridge between live chat events and the fulfillment module.

The fulfillment package imports nothing from ``bta`` by design, so the
translation lives here: :class:`ChatMessage` in, ``LiveEvent`` out, and the
resulting :class:`EventResult` turned into something the streamer can say out
loud.

**Variants are encoded in the SKU string.** ``tee-blk-l`` is one sellable
thing, not a tee that needs a size chosen later; ``tee-blk-m`` is a different
one. The SKU is treated as an opaque identifier throughout — nothing here
parses it, so any scheme works as long as each variant has its own SKU and its
own stock line. The consequence to design around is that a TikTok gift carries
no size or colour, so a gift can only ever map to one fully-specified SKU.

Two rules from ``fulfillment/README.md`` shape this file:

* ``handle_live_event`` never raises — it returns a result. An out-of-stock
  buyer must not be able to take the broadcast down, so every path here checks
  ``result.ok`` rather than relying on an exception.
* ``external_ref`` is the idempotency key. TikTok redelivers chat and
  TikTokLive replays events across reconnects, so every order carries the
  originating message id and a replay returns the original order instead of
  reserving stock twice.
"""

from __future__ import annotations

from typing import Callable

from fulfillment import (
    EventResult,
    FulfillmentService,
    InventoryStore,
    LiveEvent,
    LiveEventKind,
    Order,
    OrderStore,
    StatusChange,
)

from bta.config import CommerceConfig
from bta.events import ChatMessage, Priority
from bta.log import get_logger

log = get_logger("commerce")

Announce = Callable[[str], None]


class CommerceBridge:
    """Translates chat events into orders, and orders into things to say."""

    def __init__(
        self,
        cfg: CommerceConfig,
        *,
        announce: Announce | None = None,
        service: FulfillmentService | None = None,
    ) -> None:
        self.cfg = cfg
        self._announce = announce
        self.service = service or FulfillmentService(
            InventoryStore(dict(cfg.stock)), OrderStore()
        )
        self.session_id = cfg.session_id or "live"
        self.orders_placed = 0
        self.orders_rejected = 0
        self.duplicates_ignored = 0

        unnamed = cfg.unnamed_skus()
        if unnamed and cfg.announce_orders:
            # Variants live in the SKU, so unnamed products get read out as
            # "tee blk l" on a live stream. Worth one nudge at startup.
            log.warning(
                "No COMMERCE_SKU_NAMES entry for: %s — the streamer will say "
                "these out loud as-is.",
                ", ".join(unnamed),
            )

    def spoken_name(self, sku: str) -> str:
        """How a SKU should be said out loud."""
        named = self.cfg.sku_names.get(sku)
        if named:
            return named
        # No name configured: at least stop the separators being voiced.
        return sku.replace("-", " ").replace("_", " ").strip() or sku

    # -- session lifecycle -------------------------------------------------

    def start_session(self, session_id: str) -> None:
        """Tie subsequent orders to this broadcast."""
        self.session_id = session_id or "live"
        log.info("Commerce session: %s", self.session_id)

    def end_session(self) -> dict:
        """Summarize the broadcast, and optionally release held stock.

        SESSION_ENDED is deliberately non-destructive in the fulfillment
        module: dropping a buyer's reserved unit because a broadcast ended is
        a policy decision. Whether we release is therefore a config flag —
        it decides if a buyer whose stream dropped keeps their unit.
        """
        result = self.service.handle_live_event(
            LiveEvent(kind=LiveEventKind.SESSION_ENDED, session_id=self.session_id)
        )
        summary = dict(result.detail) if result.ok else {}

        if self.cfg.release_holds_on_end:
            released = self.service.release_open_holds(
                self.session_id, reason="broadcast ended"
            )
            if released:
                log.info("Released %d open hold(s) at end of stream", len(released))
            summary["released"] = len(released)
        return summary

    # -- observation -------------------------------------------------------

    def subscribe(self, listener: Callable[[Order, StatusChange], None]):
        """Push order status changes to an overlay or dashboard.

        Fires on every committed status change; a subscriber that raises is
        isolated by the service and cannot break order processing. Prefer this
        over polling the order store.
        """
        return self.service.subscribe(listener)

    def summary(self) -> dict:
        return self.service.session_summary(self.session_id)

    # -- inbound chat ------------------------------------------------------

    def sku_for(self, message: ChatMessage) -> tuple[str, int] | None:
        """Resolve a chat event to a (sku, quantity), or None if it is not a sale.

        A SKU is only ever taken from something explicit — a ``meta['sku']``
        set upstream, or an operator-configured gift mapping. Nothing is
        inferred from message text: guessing a purchase out of chatter would
        reserve real stock against a joke.
        """
        explicit = message.meta.get("sku", "").strip()
        if explicit:
            return explicit, _quantity(message.meta.get("qty"))

        if message.kind == "gift" and self.cfg.gift_skus:
            gift_name = message.meta.get("gift", "").strip().lower()
            sku = self.cfg.gift_skus.get(gift_name, "")
            if sku:
                # One unit per gift sent, so a 5x Rose combo ships five.
                return sku, _quantity(message.meta.get("count"))
        return None

    def on_chat_message(self, message: ChatMessage) -> EventResult | None:
        """Handle one chat event. Returns None if it was not a sale at all."""
        if not self.cfg.enabled:
            return None

        resolved = self.sku_for(message)
        if resolved is None:
            return None
        sku, quantity = resolved

        external_ref = message.meta.get("event_id", "").strip()
        if not external_ref:
            # Without TikTok's own id a redelivered gift would create a second
            # order and hold stock twice. A synthetic ref is still stable per
            # (user, sku, arrival) and far better than passing None.
            external_ref = f"bta:{message.user}:{sku}:{message.received_at:.3f}"
            log.debug("No upstream event id; using synthetic ref %s", external_ref)

        result = self.service.handle_live_event(
            LiveEvent(
                kind=LiveEventKind.ORDER_PLACED,
                session_id=self.session_id,
                payload={
                    "sku": sku,
                    "quantity": quantity,
                    "buyer_handle": message.user,
                    "unit_price_cents": self.cfg.prices.get(sku, 0),
                },
                external_ref=external_ref,
            )
        )
        self._record(result, message, sku, quantity)
        return result

    # -- outcomes ----------------------------------------------------------

    def _record(
        self, result: EventResult, message: ChatMessage, sku: str, quantity: int
    ) -> None:
        if result.duplicate:
            self.duplicates_ignored += 1
            log.info("Ignored redelivered order for %s (%s)", message.user, sku)
            return

        if not result.ok:
            self.orders_rejected += 1
            reason = result.detail.get("error_type", "error")
            log.warning(
                "Order rejected for %s (%s x%d): %s [%s]",
                message.user,
                sku,
                quantity,
                result.error,
                reason,
            )
            self._say(self._rejection_line(message, sku, reason))
            return

        self.orders_placed += 1
        order = result.order
        log.info(
            "Order %s captured for %s: %s x%d",
            getattr(order, "id", "?"),
            message.user,
            sku,
            quantity,
        )

        # A gift is already paid for — TikTok settled it before we ever saw the
        # event — so there is no later payment step to wait on. Leaving it
        # RESERVED would hold that unit forever.
        settled = False
        if order is not None and message.kind == "gift" and self.cfg.auto_fulfill_gifts:
            settled = self.fulfill(order.id, reason="gift settled by TikTok") is not None

        self._say(self._confirmation_line(message, sku, quantity, settled=settled))

    def fulfill(self, order_id: str, reason: str = "fulfilled") -> Order | None:
        """Convert a reservation into a real depletion."""
        return self._transition(self.service.fulfill, order_id, reason, "fulfill")

    def cancel(self, order_id: str, reason: str = "cancelled") -> Order | None:
        """Release a hold because someone pulled the order."""
        return self._transition(self.service.cancel, order_id, reason, "cancel")

    def mark_failed(self, order_id: str, reason: str) -> Order | None:
        """Release a hold because the system could not complete the sale."""
        return self._transition(self.service.mark_failed, order_id, reason, "fail")

    def _transition(self, method, order_id: str, reason: str, label: str) -> Order | None:
        # The direct API raises, unlike handle_live_event. Contain it here so a
        # bad transition cannot reach the stream loop.
        try:
            return method(order_id, reason)
        except Exception as exc:
            log.error("Could not %s order %s: %s", label, order_id, exc)
            return None

    # -- speech ------------------------------------------------------------

    def _say(self, line: str) -> None:
        if line and self._announce is not None:
            self._announce(line)

    def _confirmation_line(
        self, message: ChatMessage, sku: str, quantity: int, *, settled: bool
    ) -> str:
        if not self.cfg.announce_orders:
            return ""
        item = self.spoken_name(sku)
        countable = f"{quantity}x {item}" if quantity > 1 else item
        state = (
            "confirmed and on the way"
            if settled
            else "held for them while the order is confirmed"
        )
        return (
            f"{message.user} just claimed {countable}. Thank them by name and "
            f"tell them it is {state}."
        )

    def _rejection_line(self, message: ChatMessage, sku: str, reason: str) -> str:
        if not self.cfg.announce_orders:
            return ""
        # Only a real stock-out is the audience's business. An unknown SKU means
        # a gift was mapped to something inventory has never heard of — an
        # operator misconfiguration, and telling viewers an item they never
        # could have bought is "sold out" would be a lie.
        if reason != "InsufficientStock":
            return ""
        item = self.spoken_name(sku)
        return (
            f"{message.user} tried to claim {item} but it is sold out. "
            "Let them down warmly and point them at what is still available."
        )

    # -- stock -------------------------------------------------------------

    def sync_stock(self, levels: dict[str, int]) -> EventResult:
        """Reconcile on-hand counts against an external source of truth."""
        return self.service.handle_live_event(
            LiveEvent(
                kind=LiveEventKind.STOCK_SYNC,
                session_id=self.session_id,
                payload={"levels": levels},
            )
        )


def _quantity(raw: object) -> int:
    """Chat metadata is all strings and may be junk; never trust it."""
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        return 1
    return max(1, value)


def announcement_message(text: str) -> ChatMessage:
    """Wrap an announcement so the director treats it as top-priority."""
    return ChatMessage(
        user="system",
        text=text,
        kind="system",
        priority=Priority.GIFT,
    )
