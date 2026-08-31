"""Chat filtering, rate limiting and batching."""

from __future__ import annotations

from bta.config import DirectorConfig
from bta.director import Director
from bta.events import ChatMessage, Priority


def chat(user: str, text: str) -> ChatMessage:
    return ChatMessage(user=user, text=text, kind="chat")


def gift(user: str, text: str = "sent 5x Rose") -> ChatMessage:
    return ChatMessage(user=user, text=text, kind="gift", priority=Priority.GIFT)


def make(**overrides) -> Director:
    cfg = DirectorConfig(**overrides)
    return Director(cfg)


def test_plain_message_is_accepted():
    director = make()
    assert director.accept(chat("alice", "hey how are you"))
    assert director.pending == 1


def test_empty_and_whitespace_messages_are_dropped():
    director = make()
    assert not director.accept(chat("alice", "   "))
    assert director.pending == 0


def test_urls_are_stripped():
    director = make()
    director.accept(chat("alice", "check out https://spam.example/x now"))
    prompt = director.next_prompt()
    assert "spam.example" not in prompt
    assert "check out" in prompt


def test_message_with_only_a_url_is_dropped():
    director = make()
    assert not director.accept(chat("alice", "https://spam.example/x"))


def test_blocked_words_reject_the_message():
    director = make(blocked_words=("badword",))
    assert not director.accept(chat("alice", "you are a BADWORD"))
    assert director.rejected == 1


def test_long_messages_are_truncated():
    director = make(max_message_chars=20)
    # Varied text, so the repeated-character collapse does not shorten it first.
    director.accept(chat("alice", "the quick brown fox jumps over the lazy dog again"))
    prompt = director.next_prompt()
    assert "..." in prompt
    spoken = prompt.split("alice: ")[1].strip()
    assert len(spoken) <= 23  # 20 chars plus the ellipsis
    assert "lazy dog" not in spoken


def test_repeated_characters_are_collapsed():
    director = make()
    director.accept(chat("alice", "loooooooool"))
    assert "loooooooool" not in director.next_prompt()


def test_same_user_is_rate_limited():
    director = make(user_cooldown=10.0)
    assert director.accept(chat("alice", "first"), now=100.0)
    assert not director.accept(chat("alice", "second"), now=101.0)
    assert director.accept(chat("alice", "third"), now=115.0)


def test_different_users_are_not_rate_limited():
    director = make(user_cooldown=10.0)
    assert director.accept(chat("alice", "hi"), now=100.0)
    assert director.accept(chat("bob", "hello"), now=100.5)


def test_duplicate_text_is_deduplicated_across_users():
    director = make(user_cooldown=0.0)
    assert director.accept(chat("alice", "first one"), now=100.0)
    assert not director.accept(chat("bob", "FIRST ONE"), now=101.0)


def test_dedupe_window_expires():
    director = make(user_cooldown=0.0, dedupe_window=30.0)
    assert director.accept(chat("alice", "same text"), now=100.0)
    assert director.accept(chat("bob", "same text"), now=200.0)


def test_gifts_bypass_the_chat_cooldown():
    director = make(user_cooldown=60.0)
    assert director.accept(chat("alice", "hello"), now=100.0)
    assert director.accept(gift("alice"), now=101.0)


def test_gifts_can_be_disabled():
    director = make(greet_gifts=False)
    assert not director.accept(gift("alice"))


def test_follows_can_be_disabled():
    director = make(greet_follows=False)
    follow = ChatMessage(user="a", text="followed", kind="follow", priority=Priority.FOLLOW)
    assert not director.accept(follow)


def test_batch_is_capped_and_prioritized():
    director = make(max_batch=2, user_cooldown=0.0)
    for i in range(5):
        director.accept(chat(f"user{i}", f"message number {i}"), now=100.0 + i)
    director.accept(gift("whale"), now=110.0)

    prompt = director.next_prompt()
    assert "[gift] whale" in prompt, "a gift should outrank plain chat"
    assert prompt.count("\n") >= 1
    # Only max_batch lines of chat data should be included.
    body = prompt.rsplit("\n\n", 1)[-1]
    assert len(body.strip().splitlines()) == 2


def test_leftovers_stay_queued_for_the_next_turn():
    director = make(max_batch=2, user_cooldown=0.0)
    for i in range(5):
        director.accept(chat(f"user{i}", f"msg {i}"), now=100.0 + i)
    director.next_prompt()
    assert director.pending == 3


def test_idle_prompt_after_silence():
    director = make(idle_prompt_after=30.0)
    director.last_activity = 100.0
    assert director.next_prompt(now=110.0) is None
    assert director.next_prompt(now=140.0) is not None


def test_idle_prompt_uses_custom_text():
    director = make(idle_prompt_after=1.0, idle_prompts=("CUSTOM IDLE",))
    director.last_activity = 0.0
    assert director.next_prompt(now=100.0) == "CUSTOM IDLE"


def test_queue_drops_oldest_when_full():
    director = make(queue_size=3, user_cooldown=0.0)
    for i in range(10):
        director.accept(chat(f"user{i}", f"message {i}"), now=100.0 + i)
    assert director.pending == 3
    assert director.queue.dropped == 7


def test_control_characters_are_scrubbed():
    director = make()
    director.accept(chat("alice", "he​llo the﻿re"))
    prompt = director.next_prompt()
    assert "​" not in prompt and "" not in prompt and "﻿" not in prompt
    assert "he llo" in prompt or "hello" in prompt


def test_cooldown_map_is_pruned_on_a_long_stream():
    director = make(user_cooldown=1.0)
    for i in range(6000):
        director.accept(chat(f"user{i}", f"message {i}"), now=1000.0 + i * 0.001)
    assert len(director._last_seen_from) <= 5001
