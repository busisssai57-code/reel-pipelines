"""End-to-end wiring: chat in, audio out, avatar moving.

The Gemini session is replaced with a fake that emits synthetic speech, so the
whole chain runs offline: director -> brain callbacks -> player -> lip sync ->
VTube Studio.
"""

from __future__ import annotations

import asyncio
import math
import struct

import pytest

from bta.config import Config, OUTPUT_SAMPLE_RATE
from bta.events import ChatMessage, Priority
from bta.pipeline import Pipeline
from tools.mock_vts import MockVTubeStudio


def speech_like(seconds: float = 1.0) -> bytes:
    """Amplitude-modulated tone: loud syllables with gaps, like real speech."""
    out = bytearray()
    for i in range(int(seconds * OUTPUT_SAMPLE_RATE)):
        t = i / OUTPUT_SAMPLE_RATE
        envelope = max(0.0, math.sin(2 * math.pi * 3.5 * t)) ** 2
        out += struct.pack(
            "<h", int(0.8 * 32767 * envelope * math.sin(2 * math.pi * 140 * t))
        )
    return bytes(out)


@pytest.fixture
async def rig(tmp_path):
    """A pipeline wired to a mock VTube Studio, writing audio to a wav file."""
    mock = MockVTubeStudio()
    await mock.start()

    cfg = Config()
    cfg.gemini.api_key = "test-key"
    cfg.vtube.port = mock.port
    cfg.vtube.token_file = str(tmp_path / "token")
    cfg.vtube.inject_fps = 60
    cfg.audio.sink = "wav"
    cfg.audio.wav_path = str(tmp_path / "audio.wav")

    pipeline = Pipeline(cfg, use_console_source=True)
    pipeline.player.start()
    avatar = asyncio.create_task(pipeline._avatar_loop())
    await asyncio.sleep(0.6)  # let VTS authenticate

    yield pipeline, mock

    avatar.cancel()
    with pytest.raises(asyncio.CancelledError):
        await avatar
    pipeline.player.stop()
    await pipeline.vts.close()
    await mock.stop()


async def drain(pipeline: Pipeline, timeout: float = 6.0) -> None:
    loop = asyncio.get_running_loop()
    start = loop.time()
    while pipeline.player.pending_bytes > 0 or pipeline.player.speaking:
        if loop.time() - start > timeout:
            break
        await asyncio.sleep(0.02)


async def test_model_audio_drives_the_avatar_mouth(rig):
    pipeline, mock = rig
    assert pipeline.vts.connected, "VTS should be connected"

    pipeline.player.feed(speech_like(1.0))
    await asyncio.sleep(0.3)
    assert pipeline.player.mouth_open > 0.3, "mouth should open while speaking"

    await drain(pipeline)
    await asyncio.sleep(0.4)

    assert mock.injections, "no parameters reached VTube Studio"
    values = [
        p["value"]
        for injection in mock.injections
        for p in injection["parameterValues"]
        if p["id"] == "MouthOpen"
    ]
    assert max(values) > 0.5, "mouth never opened meaningfully"
    assert min(values) == 0.0, "mouth never closed"
    # Syllables should make it move, not sit at one value.
    assert len({round(v, 1) for v in values}) > 3, "mouth barely moved"


async def test_mouth_returns_to_closed_after_speaking(rig):
    pipeline, mock = rig
    pipeline.player.feed(speech_like(0.5))
    await drain(pipeline)
    await asyncio.sleep(0.6)
    assert pipeline.player.mouth_open == 0.0
    assert mock.last_parameters["MouthOpen"] == 0.0


async def test_injection_stops_while_the_avatar_is_silent(rig):
    """A permanently silent mouth must not be re-injected forever, or VTube
    Studio's own face tracking never gets the model back."""
    pipeline, mock = rig
    await asyncio.sleep(0.8)  # past CLOSED_HOLD_SECONDS with no audio
    settled = len(mock.injections)
    await asyncio.sleep(0.5)
    assert len(mock.injections) == settled, "kept injecting while silent"

    # Speaking again must resume injection immediately.
    pipeline.player.feed(speech_like(0.4))
    await asyncio.sleep(0.25)
    assert len(mock.injections) > settled
    await drain(pipeline)


async def test_audio_is_written_to_the_sink(rig):
    pipeline, _ = rig
    pcm = speech_like(0.5)
    pipeline.player.feed(pcm)
    await drain(pipeline)
    await asyncio.sleep(0.1)
    assert pipeline.sink.bytes_written >= len(pcm) - pipeline.player.frame_bytes


async def test_playback_is_paced_in_real_time(rig):
    pipeline, _ = rig
    loop = asyncio.get_running_loop()
    start = loop.time()
    pipeline.player.feed(speech_like(1.0))
    await drain(pipeline)
    elapsed = loop.time() - start
    assert 0.85 <= elapsed <= 1.5, f"1s of speech played in {elapsed:.2f}s"


async def test_interruption_stops_the_mouth(rig):
    pipeline, _ = rig
    pipeline.player.feed(speech_like(3.0))
    await asyncio.sleep(0.3)
    assert pipeline.player.mouth_open > 0.0

    pipeline._on_interrupted()
    assert pipeline.player.mouth_open == 0.0
    assert pipeline.player.pending_bytes == 0


async def test_chat_flows_through_the_director_to_a_prompt(rig):
    pipeline, _ = rig
    pipeline._on_chat(ChatMessage(user="alice", text="what game is this?", kind="chat"))
    pipeline._on_chat(
        ChatMessage(user="bob", text="sent 5x Rose", kind="gift", priority=Priority.GIFT)
    )
    # Skip past the deliberate reply delay; pacing has its own tests.
    pipeline.director._next_turn_at = 0.0
    prompt = pipeline.director.next_prompt()
    assert prompt is not None
    assert "alice" in prompt and "what game is this?" in prompt
    assert "[gift] bob" in prompt


async def test_director_holds_off_while_the_avatar_is_speaking(rig):
    pipeline, _ = rig
    pipeline.brain.connected = True
    pipeline.player.feed(speech_like(2.0))
    await asyncio.sleep(0.2)

    pipeline._on_chat(ChatMessage(user="alice", text="hello there", kind="chat"))
    director = asyncio.create_task(pipeline._director_loop())
    await asyncio.sleep(0.5)
    director.cancel()
    with pytest.raises(asyncio.CancelledError):
        await director

    # The message must still be waiting: we do not talk over ourselves.
    assert pipeline.director.pending == 1
    pipeline.player.interrupt()


async def test_unsafe_output_is_cut_mid_sentence(rig):
    """Native audio plays before a full response exists, so the only real
    control is cutting playback the moment the transcript goes wrong."""
    pipeline, _ = rig
    pipeline.player.feed(speech_like(3.0))
    await asyncio.sleep(0.25)
    assert pipeline.player.mouth_open > 0.0

    pipeline._on_turn_start()
    pipeline._on_text("you should ")
    assert pipeline.player.pending_bytes > 0, "still speaking, nothing wrong yet"
    pipeline._on_text("kill yourself")

    assert pipeline._turn_cut
    assert pipeline.player.pending_bytes == 0, "audio should have been dropped"
    assert pipeline.player.mouth_open == 0.0


async def test_safe_output_is_not_cut(rig):
    pipeline, _ = rig
    pipeline.player.feed(speech_like(1.0))
    await asyncio.sleep(0.2)
    pipeline._on_turn_start()
    pipeline._on_text("Hey everyone, welcome in! ")
    pipeline._on_text("What are we playing today?")

    assert not pipeline._turn_cut
    assert pipeline.player.pending_bytes > 0
    await drain(pipeline)


async def test_a_cut_turn_does_not_reappear_in_the_next_one(rig):
    pipeline, _ = rig
    pipeline._on_turn_start()
    pipeline._on_text("kill yourself")
    assert pipeline._turn_cut

    pipeline._on_turn_start()
    assert not pipeline._turn_cut
    pipeline._on_text("Welcome back everyone")
    assert not pipeline._turn_cut


async def test_transcript_is_assembled_across_chunks(rig):
    pipeline, _ = rig
    pipeline._on_text("Hey ")
    pipeline._on_text("everyone")
    assert pipeline._transcript == "Hey everyone"
    pipeline._on_turn_complete()
    assert pipeline._transcript == "", "transcript should reset between turns"


async def test_vts_reconnects_after_the_server_drops(tmp_path):
    """VTube Studio being closed mid-stream must not kill the pipeline."""
    mock = MockVTubeStudio()
    await mock.start()
    port = mock.port

    cfg = Config()
    cfg.gemini.api_key = "test-key"
    cfg.vtube.port = port
    cfg.vtube.token_file = str(tmp_path / "token")
    cfg.audio.sink = "null"

    pipeline = Pipeline(cfg, use_console_source=True)
    pipeline.player.start()
    avatar = asyncio.create_task(pipeline._avatar_loop())
    try:
        await asyncio.sleep(0.6)
        assert pipeline.vts.connected

        await mock.stop()
        pipeline.player.feed(speech_like(0.3))
        await asyncio.sleep(0.5)
        assert not avatar.done(), "the avatar task should survive VTS going away"

        # Bring VTube Studio back on the same port.
        revived = MockVTubeStudio()
        await revived.start(port=port)
        try:
            for _ in range(60):
                await asyncio.sleep(0.25)
                if pipeline.vts.connected:
                    break
            assert pipeline.vts.connected, "should have reconnected to VTS"
        finally:
            await revived.stop()
    finally:
        avatar.cancel()
        with pytest.raises(asyncio.CancelledError):
            await avatar
        pipeline.player.stop()
        await pipeline.vts.close()
