"""TikTok Live chat capture.

Normalizes the handful of TikTokLive events we care about into ChatMessage.
The event objects are generated protobuf classes whose optional fields are
often None, so every field read goes through a defensive helper.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Callable

from TikTokLive import TikTokLiveClient
from TikTokLive.client.errors import UserOfflineError
from TikTokLive.events import (
    CommentEvent,
    ConnectEvent,
    DisconnectEvent,
    FollowEvent,
    GiftEvent,
    LiveEndEvent,
    ShareEvent,
)

from bta.config import TikTokConfig
from bta.events import ChatMessage, Priority
from bta.log import get_logger

log = get_logger("source.tiktok")

Emit = Callable[[ChatMessage], None]


def _event_id(event: object) -> str:
    """TikTok's own message id, used as the fulfillment idempotency key.

    Chat is redelivered and TikTokLive replays events across reconnects, so an
    order placed without this would be captured twice on a reconnect.
    """
    common = getattr(event, "common", None)
    message_id = getattr(common, "msg_id", None) if common is not None else None
    return str(message_id) if message_id else ""


def _user_name(event: object) -> str:
    """Best display name available for whoever triggered the event."""
    user = getattr(event, "user", None)
    if user is None:
        return "someone"
    for attribute in ("nickname", "unique_id", "display_id", "id"):
        value = getattr(user, attribute, None)
        if value:
            return str(value).strip()
    return "someone"


class TikTokSource:
    """Connects to a live room and emits normalized chat events."""

    def __init__(self, cfg: TikTokConfig, emit: Emit) -> None:
        self.cfg = cfg
        self.emit = emit
        self.client = TikTokLiveClient(unique_id=cfg.handle)
        self.connected = False
        self.messages_seen = 0
        self._stop = asyncio.Event()
        self._register()

        if cfg.session_id:
            # Only needed for rooms that require a logged-in viewer.
            with contextlib.suppress(Exception):
                self.client.web.set_session(cfg.session_id)

    # -- event wiring ------------------------------------------------------

    def _register(self) -> None:
        client = self.client

        @client.on(ConnectEvent)
        async def _on_connect(_event: ConnectEvent) -> None:
            self.connected = True
            log.info("Connected to %s (room %s)", self.cfg.handle, client.room_id)

        @client.on(DisconnectEvent)
        async def _on_disconnect(_event: DisconnectEvent) -> None:
            self.connected = False
            log.warning("Disconnected from TikTok")

        @client.on(LiveEndEvent)
        async def _on_live_end(_event: LiveEndEvent) -> None:
            self.connected = False
            log.warning("The live stream ended")

        @client.on(CommentEvent)
        async def _on_comment(event: CommentEvent) -> None:
            text = (event.comment or "").strip()
            if not text:
                return
            self.messages_seen += 1
            priority = Priority.QUESTION if "?" in text else Priority.CHAT
            self.emit(
                ChatMessage(
                    user=_user_name(event),
                    text=text,
                    kind="chat",
                    priority=priority,
                    meta={"event_id": _event_id(event)},
                )
            )

        @client.on(GiftEvent)
        async def _on_gift(event: GiftEvent) -> None:
            gift = getattr(event, "gift", None)
            # Streakable gifts fire repeatedly; only react when the streak ends.
            if getattr(event, "streaking", False):
                return
            name = str(getattr(gift, "name", "") or "a gift")
            count = int(getattr(event, "repeat_count", 0) or 1)
            self.emit(
                ChatMessage(
                    user=_user_name(event),
                    text=f"sent {count}x {name}",
                    kind="gift",
                    priority=Priority.GIFT,
                    meta={
                        "gift": name,
                        "count": str(count),
                        "event_id": _event_id(event),
                    },
                )
            )

        @client.on(FollowEvent)
        async def _on_follow(event: FollowEvent) -> None:
            self.emit(
                ChatMessage(
                    user=_user_name(event),
                    text="just followed",
                    kind="follow",
                    priority=Priority.FOLLOW,
                )
            )

        @client.on(ShareEvent)
        async def _on_share(event: ShareEvent) -> None:
            self.emit(
                ChatMessage(
                    user=_user_name(event),
                    text="shared the stream",
                    kind="share",
                    priority=Priority.SHARE,
                )
            )

    # -- lifecycle ---------------------------------------------------------

    async def is_live(self) -> bool:
        try:
            return await self.client.is_live()
        except Exception as exc:
            log.debug("is_live check failed: %s", exc)
            return False

    async def run(self) -> None:
        """Stay connected for as long as possible, reconnecting when dropped."""
        while not self._stop.is_set():
            try:
                if self.cfg.retry_when_offline and not await self.is_live():
                    log.info(
                        "%s is not live; checking again in %.0fs",
                        self.cfg.handle,
                        self.cfg.reconnect_delay,
                    )
                    await self._sleep(self.cfg.reconnect_delay)
                    continue

                log.info("Connecting to %s ...", self.cfg.handle)
                await self.client.connect(fetch_room_info=True)
            except UserOfflineError:
                log.info("%s went offline", self.cfg.handle)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error("TikTok connection error: %s", exc)
            finally:
                self.connected = False

            if self._stop.is_set():
                return
            await self._sleep(self.cfg.reconnect_delay)

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)

    async def stop(self) -> None:
        self._stop.set()
        with contextlib.suppress(Exception):
            await self.client.disconnect()
