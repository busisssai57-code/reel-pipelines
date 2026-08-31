"""The commerce adapter: chat events in, orders out.

These exercise the boundary described in fulfillment/README.md — idempotency,
the never-raises contract, and two-phase stock — against the real
FulfillmentService rather than a stub, so a contract change shows up here.
"""

from __future__ import annotations

import pytest

from bta.commerce import CommerceBridge, announcement_message
from bta.config import CommerceConfig
from bta.events import ChatMessage, Priority
from fulfillment import OrderStatus


def make_bridge(said: list[str] | None = None, **overrides) -> CommerceBridge:
    defaults = dict(
        enabled=True,
        stock={"tee-blk-l": 5, "mug": 2},
        prices={"tee-blk-l": 2500},
        sku_names={"tee-blk-l": "black tee"},
        gift_skus={"galaxy": "tee-blk-l"},
    )
    cfg = CommerceConfig(**{**defaults, **overrides})
    bridge = CommerceBridge(cfg, announce=(said.append if said is not None else None))
    bridge.start_session("live-test")
    return bridge


def gift(user="@alice", name="Galaxy", count=1, event_id="msg-1") -> ChatMessage:
    return ChatMessage(
        user=user,
        text=f"sent {count}x {name}",
        kind="gift",
        priority=Priority.GIFT,
        meta={"gift": name, "count": str(count), "event_id": event_id},
    )


def purchase(user="@alice", sku="tee-blk-l", qty=1, event_id="buy-1") -> ChatMessage:
    return ChatMessage(
        user=user,
        text=f"bought {sku}",
        kind="purchase",
        priority=Priority.GIFT,
        meta={"sku": sku, "qty": str(qty), "event_id": event_id},
    )


def chat(user="@alice", text="hello") -> ChatMessage:
    return ChatMessage(user=user, text=text, kind="chat", meta={"event_id": "c-1"})


# -- what counts as a sale -------------------------------------------------


def test_plain_chat_is_not_an_order():
    assert make_bridge().on_chat_message(chat()) is None


def test_unmapped_gift_is_not_an_order():
    """A SKU is never guessed from a gift we were not told about."""
    assert make_bridge().on_chat_message(gift(name="Rose")) is None


def test_mapped_gift_places_an_order():
    bridge = make_bridge()
    result = bridge.on_chat_message(gift())
    assert result is not None and result.ok
    assert result.order.lines[0].sku == "tee-blk-l"
    assert result.order.buyer_handle == "@alice"


def test_gift_mapping_is_case_insensitive():
    bridge = make_bridge()
    assert bridge.on_chat_message(gift(name="GALAXY")).ok


def test_explicit_sku_in_meta_places_an_order():
    bridge = make_bridge()
    result = bridge.on_chat_message(purchase(sku="mug", qty=2))
    assert result.ok
    assert result.order.lines[0].sku == "mug"
    assert result.order.lines[0].quantity == 2


def test_gift_count_becomes_quantity():
    bridge = make_bridge()
    result = bridge.on_chat_message(gift(count=3))
    assert result.order.lines[0].quantity == 3


def test_disabled_bridge_ignores_everything():
    bridge = make_bridge(enabled=False)
    assert bridge.on_chat_message(gift()) is None


@pytest.mark.parametrize("raw", ["", "not-a-number", None, "-4", "0"])
def test_junk_quantities_fall_back_to_one(raw):
    """Chat metadata is untrusted strings; a bad count must not reserve 0 or -4."""
    bridge = make_bridge()
    message = gift()
    message.meta["count"] = raw
    result = bridge.on_chat_message(message)
    assert result.order.lines[0].quantity == 1


# -- idempotency -----------------------------------------------------------


def test_redelivered_event_does_not_order_twice():
    bridge = make_bridge()
    first = bridge.on_chat_message(gift(event_id="msg-7"))
    second = bridge.on_chat_message(gift(event_id="msg-7"))

    assert second.duplicate
    assert second.order.id == first.order.id
    assert bridge.orders_placed == 1
    assert bridge.duplicates_ignored == 1


def test_replay_does_not_reserve_stock_twice():
    bridge = make_bridge(auto_fulfill_gifts=False)
    bridge.on_chat_message(gift(event_id="msg-7"))
    reserved_once = bridge.service.inventory.level("tee-blk-l").reserved
    bridge.on_chat_message(gift(event_id="msg-7"))
    assert bridge.service.inventory.level("tee-blk-l").reserved == reserved_once


def test_distinct_events_from_one_user_are_separate_orders():
    bridge = make_bridge()
    first = bridge.on_chat_message(gift(event_id="msg-1"))
    second = bridge.on_chat_message(gift(event_id="msg-2"))
    assert first.order.id != second.order.id
    assert bridge.orders_placed == 2


def test_missing_event_id_still_gets_a_stable_ref():
    """Without TikTok's id we synthesize one rather than passing None."""
    bridge = make_bridge()
    message = gift()
    message.meta.pop("event_id")
    result = bridge.on_chat_message(message)
    assert result.ok
    assert result.order.external_ref, "an order must always carry a ref"


# -- failure is returned, never raised -------------------------------------


def test_overselling_is_rejected_without_raising():
    bridge = make_bridge()
    result = bridge.on_chat_message(gift(count=99))
    assert result.ok is False
    assert result.detail["error_type"] == "InsufficientStock"
    assert bridge.orders_rejected == 1


def test_unknown_sku_is_rejected_without_raising():
    bridge = make_bridge()
    result = bridge.on_chat_message(purchase(sku="does-not-exist"))
    assert result.ok is False
    assert result.order is None


def test_a_rejected_order_leaves_stock_untouched():
    bridge = make_bridge()
    before = bridge.service.inventory.level("tee-blk-l")
    bridge.on_chat_message(gift(count=99))
    after = bridge.service.inventory.level("tee-blk-l")
    assert (after.on_hand, after.reserved) == (before.on_hand, before.reserved)


def test_a_bad_transition_is_contained():
    """The direct API raises; the bridge must absorb it."""
    bridge = make_bridge()
    assert bridge.fulfill("no-such-order") is None
    assert bridge.cancel("no-such-order") is None
    assert bridge.mark_failed("no-such-order", "nope") is None


# -- two-phase stock -------------------------------------------------------


def test_gift_orders_are_auto_fulfilled():
    """A gift is already paid for, so nothing is left holding stock."""
    bridge = make_bridge()
    result = bridge.on_chat_message(gift())
    order = bridge.service.orders.get(result.order.id)
    assert order.status is OrderStatus.FULFILLED
    level = bridge.service.inventory.level("tee-blk-l")
    assert (level.on_hand, level.reserved) == (4, 0)


def test_auto_fulfill_can_be_turned_off():
    bridge = make_bridge(auto_fulfill_gifts=False)
    result = bridge.on_chat_message(gift())
    assert bridge.service.orders.get(result.order.id).status is OrderStatus.RESERVED
    assert bridge.service.inventory.level("tee-blk-l").reserved == 1


def test_non_gift_orders_stay_reserved_pending_payment():
    bridge = make_bridge()
    result = bridge.on_chat_message(purchase())
    assert bridge.service.orders.get(result.order.id).status is OrderStatus.RESERVED


def test_cancelling_releases_the_hold():
    bridge = make_bridge()
    result = bridge.on_chat_message(purchase())
    bridge.cancel(result.order.id, "buyer changed their mind")
    assert bridge.service.inventory.level("tee-blk-l").reserved == 0


def test_marking_failed_releases_the_hold():
    bridge = make_bridge()
    result = bridge.on_chat_message(purchase())
    bridge.mark_failed(result.order.id, "payment declined")
    assert bridge.service.inventory.level("tee-blk-l").reserved == 0


# -- session end -----------------------------------------------------------


def test_session_end_keeps_holds_by_default():
    """A dropped broadcast must not silently take back a buyer's unit."""
    bridge = make_bridge(auto_fulfill_gifts=False)
    bridge.on_chat_message(gift())
    bridge.end_session()
    assert bridge.service.inventory.level("tee-blk-l").reserved == 1


def test_session_end_releases_holds_when_configured():
    bridge = make_bridge(auto_fulfill_gifts=False, release_holds_on_end=True)
    bridge.on_chat_message(gift())
    summary = bridge.end_session()
    assert bridge.service.inventory.level("tee-blk-l").reserved == 0
    assert summary["released"] == 1


def test_session_end_does_not_undo_fulfilled_orders():
    bridge = make_bridge(release_holds_on_end=True)
    result = bridge.on_chat_message(gift())
    bridge.end_session()
    assert bridge.service.orders.get(result.order.id).status is OrderStatus.FULFILLED


# -- reporting and overlay -------------------------------------------------


def test_summary_counts_revenue_for_fulfilled_orders_only():
    bridge = make_bridge()
    bridge.on_chat_message(gift(event_id="a"))  # auto-fulfilled
    bridge.on_chat_message(purchase(event_id="b"))  # left reserved
    summary = bridge.summary()
    assert summary["units_fulfilled"] == 1
    assert summary["revenue_cents"] == 2500


def test_subscribers_see_status_changes():
    bridge = make_bridge()
    seen: list[tuple[str, str]] = []
    bridge.subscribe(lambda order, change: seen.append((order.id, change.to_status.value)))
    bridge.on_chat_message(gift())
    assert [status for _id, status in seen][-1] == "fulfilled"


def test_a_raising_subscriber_cannot_break_orders():
    bridge = make_bridge()

    def bad_subscriber(order, change):
        raise RuntimeError("overlay exploded")

    bridge.subscribe(bad_subscriber)
    result = bridge.on_chat_message(gift())
    assert result.ok, "a broken overlay must not stop the sale"


def test_stock_sync_reconciles_levels():
    bridge = make_bridge()
    result = bridge.sync_stock({"tee-blk-l": 20})
    assert result.ok
    assert bridge.service.inventory.level("tee-blk-l").on_hand == 20


# -- what the streamer says ------------------------------------------------


def test_a_confirmed_order_produces_something_to_say():
    said: list[str] = []
    bridge = make_bridge(said)
    bridge.on_chat_message(gift())
    assert said and "@alice" in said[0]
    assert "black tee" in said[0], "should use the human name, not the sku"


def test_a_reserved_order_is_not_described_as_on_its_way():
    said: list[str] = []
    bridge = make_bridge(said, auto_fulfill_gifts=False)
    bridge.on_chat_message(gift())
    assert "held" in said[0]


def test_a_sold_out_order_produces_an_apology():
    said: list[str] = []
    bridge = make_bridge(said)
    bridge.on_chat_message(gift(count=99))
    assert said and "sold out" in said[0]


def test_internal_errors_are_not_announced_to_viewers():
    said: list[str] = []
    bridge = make_bridge(said)
    bridge.on_chat_message(purchase(sku="does-not-exist"))
    assert said == [], "an unknown sku is an operator problem, not chat's"


def test_announcements_can_be_silenced():
    said: list[str] = []
    bridge = make_bridge(said, announce_orders=False)
    bridge.on_chat_message(gift())
    assert said == []


def test_announcement_message_is_high_priority_and_unattributed():
    message = announcement_message("Thank @alice for the order.")
    assert message.priority is Priority.GIFT
    assert message.kind == "system"
    # It is a stage direction, not a line a viewer typed.
    assert "system:" not in message.render()
    assert "Thank @alice" in message.render()
