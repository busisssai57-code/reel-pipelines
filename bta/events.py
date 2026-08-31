"""Normalized events passed between pipeline stages."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum


class Priority(IntEnum):
    """Higher wins when the director picks what to react to."""

    CHAT = 0
    QUESTION = 1
    MENTION = 2
    FOLLOW = 3
    SHARE = 3
    GIFT = 5


@dataclass(slots=True)
class ChatMessage:
    """One thing a viewer did, normalized across TikTok event types."""

    user: str
    text: str
    kind: str = "chat"  # chat | gift | follow | share | join | system
    priority: Priority = Priority.CHAT
    received_at: float = field(default_factory=time.monotonic)
    meta: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        """One line as the model sees it."""
        if self.kind == "chat":
            return f"{self.user}: {self.text}"
        return f"[{self.kind}] {self.user}: {self.text}" if self.text else f"[{self.kind}] {self.user}"


@dataclass(slots=True)
class SpeechChunk:
    """A slice of model audio output. 24 kHz, mono, 16-bit LE."""

    pcm: bytes
    turn_id: int


class DroppingQueue:
    """Bounded async queue that drops the oldest item instead of blocking.

    Live chat never stops. If the brain is slow we would rather lose stale
    messages than build an ever-growing backlog of things to say about
    something that scrolled past two minutes ago.
    """

    def __init__(self, maxsize: int) -> None:
        self._items: deque[ChatMessage] = deque(maxlen=max(1, maxsize))
        self._event = asyncio.Event()
        self.dropped = 0

    def put(self, item: ChatMessage) -> None:
        if len(self._items) == self._items.maxlen:
            self.dropped += 1
        self._items.append(item)
        self._event.set()

    async def get(self) -> ChatMessage:
        while not self._items:
            self._event.clear()
            await self._event.wait()
        return self._items.popleft()

    def drain(self, limit: int) -> list[ChatMessage]:
        """Pop up to `limit` items, highest priority first, without waiting."""
        if not self._items:
            return []
        # Sort a snapshot so a burst of plain chat cannot bury a gift.
        ordered = sorted(
            self._items, key=lambda m: (-int(m.priority), m.received_at)
        )
        taken = ordered[:limit]
        keep = set(map(id, taken))
        remaining = [m for m in self._items if id(m) not in keep]
        self._items.clear()
        self._items.extend(remaining)
        return taken

    def __len__(self) -> int:
        return len(self._items)
