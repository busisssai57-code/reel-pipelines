"""Decides what the streamer reacts to, and when.

A busy TikTok room produces far more chat than anyone can answer out loud. The
director filters junk, keeps one viewer from monopolizing the stream, batches
what is left into a single prompt per turn, and fills silence when chat dries
up.
"""

from __future__ import annotations

import random
import re
import time

from bta.config import DirectorConfig
from bta.events import ChatMessage, DroppingQueue
from bta.log import get_logger

log = get_logger("director")

URL_PATTERN = re.compile(r"https?://\S+|www\.\S+|\b\S+\.(?:com|net|org|io|ru|xyz)\b", re.I)
# Collapse "aaaaaaaaaa" and other spam padding down to something readable.
REPEAT_PATTERN = re.compile(r"(.)\1{4,}")
# Control characters and zero-width/invisible spacing marks that spammers use
# to sneak past filters or to make chat unreadable when spoken aloud.
CONTROL_PATTERN = re.compile("[\\x00-\\x1f\\x7f\\u200b-\\u200f\\u2028\\u2029\\ufeff]")

DEFAULT_IDLE_PROMPTS = (
    "Chat has gone quiet. Say something to bring people back in — react to how "
    "the stream is going, or ask the chat an easy question.",
    "No new messages right now. Fill the gap with a short thought or a quick "
    "story, then invite chat to reply.",
    "Quiet moment. Welcome anyone who just showed up and ask what they want to "
    "talk about.",
)


class Director:
    """Filters and batches chat into prompts for the brain."""

    def __init__(self, cfg: DirectorConfig, persona_name: str = "Nova") -> None:
        self.cfg = cfg
        self.persona_name = persona_name
        self.queue = DroppingQueue(cfg.queue_size)
        self._last_seen_from: dict[str, float] = {}
        self._recent_texts: dict[str, float] = {}
        self._recent_events: dict[str, float] = {}
        self._idle_prompts = cfg.idle_prompts or DEFAULT_IDLE_PROMPTS
        self.last_activity = time.monotonic()
        self.accepted = 0
        self.rejected = 0

    # -- filtering ---------------------------------------------------------

    def clean(self, text: str) -> str:
        text = CONTROL_PATTERN.sub(" ", text)
        if self.cfg.strip_urls:
            text = URL_PATTERN.sub("", text)
        text = REPEAT_PATTERN.sub(r"\1\1\1", text)
        text = " ".join(text.split())
        if len(text) > self.cfg.max_message_chars:
            text = text[: self.cfg.max_message_chars].rstrip() + "..."
        return text

    def accept(self, message: ChatMessage, *, now: float | None = None) -> bool:
        """Filter, rate-limit and enqueue. Returns True if it was queued."""
        now = time.monotonic() if now is None else now

        if message.kind == "gift" and not self.cfg.greet_gifts:
            return self._reject()
        if message.kind in ("follow", "share") and not self.cfg.greet_follows:
            return self._reject()

        # TikTok redelivers events and TikTokLive replays them across
        # reconnects. Text dedupe below only covers chat, so without this a
        # replayed gift would have the streamer thank the same person twice.
        event_id = message.meta.get("event_id", "")
        if event_id:
            self._expire(now)
            if event_id in self._recent_events:
                return self._reject()
            self._recent_events[event_id] = now

        if message.kind == "chat":
            text = self.clean(message.text)
            if not text:
                return self._reject()

            lowered = text.lower()
            if any(word in lowered for word in self.cfg.blocked_words):
                log.debug("Blocked message from %s", message.user)
                return self._reject()

            # One viewer spamming should not crowd everyone else out.
            last = self._last_seen_from.get(message.user)
            if last is not None and now - last < self.cfg.user_cooldown:
                return self._reject()

            self._expire(now)
            if lowered in self._recent_texts:
                return self._reject()  # the same line already went through
            self._recent_texts[lowered] = now
            self._last_seen_from[message.user] = now
            message.text = text

        self.queue.put(message)
        self.accepted += 1
        self.last_activity = now
        return True

    def _reject(self) -> bool:
        self.rejected += 1
        return False

    def _expire(self, now: float) -> None:
        window = self.cfg.dedupe_window
        for cache in (self._recent_texts, self._recent_events):
            for key in [k for k, seen in cache.items() if now - seen > window]:
                del cache[key]
        # Keep the cooldown map from growing without bound on a long stream.
        if len(self._last_seen_from) > 5000:
            cutoff = now - self.cfg.user_cooldown
            self._last_seen_from = {
                user: seen for user, seen in self._last_seen_from.items() if seen > cutoff
            }

    # -- batching ----------------------------------------------------------

    def next_prompt(self, *, now: float | None = None) -> str | None:
        """The next thing to say, or None if there is nothing to react to."""
        now = time.monotonic() if now is None else now
        batch = self.queue.drain(self.cfg.max_batch)
        if batch:
            self.last_activity = now
            from bta.brain.persona import format_chat_batch

            return format_chat_batch([m.render() for m in batch], self.persona_name)

        if now - self.last_activity >= self.cfg.idle_prompt_after:
            self.last_activity = now
            return random.choice(list(self._idle_prompts))
        return None

    @property
    def pending(self) -> int:
        return len(self.queue)
