"""Gemini brain: session config, message handling and reconnection.

The Live API is not reachable from tests, so the session is faked. What is
verified here is our handling of the message shapes the API produces.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from bta.brain.gemini_live import BrainCallbacks, GeminiLiveBrain
from bta.brain.persona import build_system_instruction, format_chat_batch
from bta.config import Config


def make_brain(**gemini_overrides):
    cfg = Config()
    cfg.gemini.api_key = "test-key"
    for key, value in gemini_overrides.items():
        setattr(cfg.gemini, key, value)

    captured: dict[str, list] = {"audio": [], "text": [], "events": []}
    callbacks = BrainCallbacks(
        on_audio=lambda pcm: captured["audio"].append(pcm),
        on_text=lambda text: captured["text"].append(text),
        on_turn_start=lambda: captured["events"].append("start"),
        on_turn_complete=lambda: captured["events"].append("complete"),
        on_interrupted=lambda: captured["events"].append("interrupted"),
        on_ready=lambda model: captured["events"].append(f"ready:{model}"),
    )
    return GeminiLiveBrain(cfg, callbacks), captured


# -- message construction --------------------------------------------------


def test_live_config_requests_audio_only():
    brain, _ = make_brain()
    config = brain._live_config()
    # Native-audio models reject a request for TEXT and AUDIO together.
    assert [str(m) for m in config.response_modalities] == ["Modality.AUDIO"]
    assert config.output_audio_transcription is not None, "transcript needed for logs"


def test_live_config_carries_voice_and_language():
    brain, _ = make_brain(voice="Charon", language_code="en-GB")
    config = brain._live_config()
    assert config.speech_config.voice_config.prebuilt_voice_config.voice_name == "Charon"
    assert config.speech_config.language_code == "en-GB"


def test_live_config_enables_context_compression():
    """Without this a multi-hour stream hits the context limit and drops."""
    assert make_brain()[0]._live_config().context_window_compression is not None


def test_optional_features_are_off_by_default():
    config = make_brain()[0]._live_config()
    assert not config.enable_affective_dialog
    assert config.proactivity is None


def test_optional_features_can_be_enabled():
    config = make_brain(affective_dialog=True, proactivity=True)[0]._live_config()
    assert config.enable_affective_dialog
    assert config.proactivity is not None


def test_resumption_handle_is_sent_on_reconnect():
    brain, _ = make_brain()
    assert brain._live_config().session_resumption.handle is None
    brain._resumption_handle = "handle-abc"
    assert brain._live_config().session_resumption.handle == "handle-abc"


def test_system_instruction_forbids_stage_directions():
    text = build_system_instruction(make_brain(persona_name="Nova")[0].cfg.gemini)
    assert "Nova" in text
    assert "asterisk" in text.lower() or "markdown" in text.lower()
    assert "prompt" in text.lower(), "should defend against prompt injection"


def test_persona_extra_is_included():
    brain, _ = make_brain(persona_extra="You only talk about bread.")
    assert "bread" in build_system_instruction(brain.cfg.gemini)


def test_chat_batch_is_framed_as_data():
    prompt = format_chat_batch(["alice: hi", "[gift] bob: sent 1x Rose"], "Nova")
    assert "alice: hi" in prompt
    assert "[gift] bob" in prompt
    assert "Nova" in prompt


# -- receive loop ----------------------------------------------------------


def audio_message(pcm: bytes):
    part = SimpleNamespace(inline_data=SimpleNamespace(data=pcm), text=None)
    return SimpleNamespace(
        server_content=SimpleNamespace(
            model_turn=SimpleNamespace(parts=[part]),
            turn_complete=False,
            interrupted=False,
            output_transcription=None,
        ),
        session_resumption_update=None,
        go_away=None,
    )


def control_message(**overrides):
    content = {
        "model_turn": None,
        "turn_complete": False,
        "interrupted": False,
        "output_transcription": None,
    }
    content.update(overrides)
    return SimpleNamespace(
        server_content=SimpleNamespace(**content),
        session_resumption_update=None,
        go_away=None,
    )


class FakeSession:
    def __init__(self, messages):
        self._messages = messages
        self.sent: list[str] = []

    async def send_client_content(self, *, turns, turn_complete=True):
        self.sent.append(turns.parts[0].text)

    async def receive(self):
        for message in self._messages:
            yield message
            await asyncio.sleep(0)


async def test_audio_parts_reach_the_callback():
    brain, captured = make_brain()
    await brain._receive_loop(
        FakeSession(
            [
                audio_message(b"\x01\x02"),
                audio_message(b"\x03\x04"),
                control_message(turn_complete=True),
            ]
        )
    )
    assert captured["audio"] == [b"\x01\x02", b"\x03\x04"]
    assert captured["events"] == ["start", "complete"]
    assert brain.turns_completed == 1
    assert not brain.speaking


async def test_transcription_reaches_the_text_callback():
    brain, captured = make_brain()
    await brain._receive_loop(
        FakeSession(
            [
                control_message(output_transcription=SimpleNamespace(text="hello ")),
                control_message(output_transcription=SimpleNamespace(text="chat")),
                control_message(turn_complete=True),
            ]
        )
    )
    assert "".join(captured["text"]) == "hello chat"


async def test_interruption_is_reported():
    brain, captured = make_brain()
    await brain._receive_loop(
        FakeSession([audio_message(b"\x01\x02"), control_message(interrupted=True)])
    )
    assert "interrupted" in captured["events"]
    assert not brain.speaking


async def test_go_away_ends_the_loop_cleanly():
    """A GoAway must return, so run() can reconnect instead of erroring."""
    brain, _ = make_brain()
    messages = [
        audio_message(b"\x01\x02"),
        SimpleNamespace(
            server_content=None,
            session_resumption_update=None,
            go_away=SimpleNamespace(time_left="10s"),
        ),
        audio_message(b"never-reached"),
    ]
    session = FakeSession(messages)
    await brain._receive_loop(session)  # returns rather than raising


async def test_resumption_handle_is_captured():
    brain, _ = make_brain()
    await brain._receive_loop(
        FakeSession(
            [
                SimpleNamespace(
                    server_content=None,
                    session_resumption_update=SimpleNamespace(
                        resumable=True, new_handle="handle-xyz"
                    ),
                    go_away=None,
                ),
                control_message(turn_complete=True),
            ]
        )
    )
    assert brain._resumption_handle == "handle-xyz"


async def test_non_resumable_update_is_ignored():
    brain, _ = make_brain()
    await brain._receive_loop(
        FakeSession(
            [
                SimpleNamespace(
                    server_content=None,
                    session_resumption_update=SimpleNamespace(
                        resumable=False, new_handle=""
                    ),
                    go_away=None,
                ),
            ]
        )
    )
    assert brain._resumption_handle is None


# -- outbox ----------------------------------------------------------------


async def test_say_queues_and_send_loop_forwards():
    brain, _ = make_brain()
    assert brain.say("hello there")
    session = FakeSession([])
    task = asyncio.create_task(brain._send_loop(session))
    await asyncio.sleep(0.05)
    task.cancel()
    assert session.sent == ["hello there"]


async def test_outbox_rejects_when_saturated():
    brain, _ = make_brain()
    accepted = [brain.say(f"prompt {i}") for i in range(20)]
    assert accepted[0] is True
    assert accepted[-1] is False, "a saturated outbox should refuse, not block"


async def test_busy_reflects_queued_work():
    brain, _ = make_brain()
    assert not brain.busy
    brain.say("something")
    assert brain.busy


# -- failure classification ------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "1007 None. API key not valid. Please pass a valid API key.",
        "API_KEY_INVALID",
        "PERMISSION_DENIED: caller lacks access",
        "UNAUTHENTICATED",
        "Billing account not configured",
    ],
)
def test_auth_failures_are_treated_as_fatal(message):
    from bta.brain.gemini_live import _is_fatal

    assert _is_fatal(Exception(message))


@pytest.mark.parametrize(
    "message",
    [
        "models/gemini-x is not found for API version v1beta",
        "connection reset by peer",
        "503 Service Unavailable",
        "deadline exceeded",
    ],
)
def test_transient_failures_are_retryable(message):
    from bta.brain.gemini_live import _is_fatal

    assert not _is_fatal(Exception(message))


async def test_run_stops_immediately_on_an_auth_error(monkeypatch):
    """A rejected key must not spin in a reconnect loop forever."""
    from bta.brain.gemini_live import BrainAuthError

    brain, _ = make_brain()
    attempts = 0

    async def fail(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise BrainAuthError("Gemini rejected the API key")

    monkeypatch.setattr(brain, "_session_once", fail)
    await asyncio.wait_for(brain.run(), timeout=2.0)

    assert attempts == 1, "should not retry a rejected key"
    assert "rejected" in brain.fatal_error


async def test_run_retries_a_transient_error(monkeypatch):
    brain, _ = make_brain()
    attempts = 0

    async def flaky(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        # Stop on the second attempt: that proves the first failure was retried
        # while keeping the test to a single 1s backoff.
        if attempts >= 2:
            brain.stop()
        raise RuntimeError("connection reset by peer")

    monkeypatch.setattr(brain, "_session_once", flaky)
    await asyncio.wait_for(brain.run(), timeout=10.0)

    assert attempts == 2, "a transient error should be retried"
    assert brain.fatal_error == ""
