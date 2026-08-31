"""SpeechPlayer: real-time pacing, mouth values and interruption."""

from __future__ import annotations

import time

from conftest import silence, tone

from bta.audio.player import SpeechPlayer
from bta.audio.sink import NullSink, WavSink
from bta.config import OUTPUT_SAMPLE_RATE


def drain(player: SpeechPlayer, timeout: float = 5.0) -> float:
    start = time.monotonic()
    while player.pending_bytes > 0 or player.speaking:
        if time.monotonic() - start > timeout:
            break
        time.sleep(0.01)
    return time.monotonic() - start


def test_playback_runs_at_real_time():
    player = SpeechPlayer(NullSink(), frame_ms=20)
    player.start()
    try:
        player.feed(tone(1.0))
        elapsed = drain(player)
        assert 0.85 <= elapsed <= 1.4, f"1s of audio took {elapsed:.2f}s"
    finally:
        player.stop()


def test_every_fed_byte_reaches_the_sink():
    sink = NullSink()
    player = SpeechPlayer(sink, frame_ms=20)
    player.start()
    try:
        pcm = tone(0.5)
        player.feed(pcm)
        drain(player)
        time.sleep(0.1)
        # Whole frames only; at most one partial frame can remain unplayed.
        assert sink.bytes_written >= len(pcm) - player.frame_bytes
    finally:
        player.stop()


def test_mouth_opens_during_speech_and_closes_after():
    player = SpeechPlayer(NullSink(), frame_ms=20)
    player.start()
    try:
        player.feed(tone(0.6))
        time.sleep(0.25)
        assert player.mouth_open > 0.5, "mouth should be open mid-utterance"
        assert player.speaking
        drain(player)
        time.sleep(0.5)
        assert player.mouth_open == 0.0
        assert not player.speaking
    finally:
        player.stop()


def test_mouth_stays_shut_through_silent_audio():
    player = SpeechPlayer(NullSink(), frame_ms=20)
    player.start()
    try:
        player.feed(silence(0.4))
        time.sleep(0.2)
        assert player.mouth_open == 0.0
        drain(player)
    finally:
        player.stop()


def test_interrupt_drops_pending_audio():
    player = SpeechPlayer(NullSink(), frame_ms=20)
    player.start()
    try:
        player.feed(tone(3.0))
        time.sleep(0.1)
        assert player.pending_seconds > 1.0
        assert player.mouth_open > 0.5, "mouth should be open before the cut"
        player.interrupt()
        assert player.pending_bytes == 0
        # The audio stops immediately, so the mouth must too — no silent
        # mouthing after the model is cut off.
        assert player.mouth_open == 0.0
        time.sleep(0.2)
        assert player.mouth_open == 0.0
        assert not player.speaking
    finally:
        player.stop()


def test_gain_is_applied():
    quiet_sink, loud_sink = NullSink(), NullSink()
    quiet = SpeechPlayer(quiet_sink, frame_ms=20, gain=0.05)
    loud = SpeechPlayer(loud_sink, frame_ms=20, gain=1.0)
    quiet.start()
    loud.start()
    try:
        pcm = tone(0.3, amplitude=0.5)
        quiet.feed(pcm)
        loud.feed(pcm)
        time.sleep(0.15)
        assert quiet.mouth_open < loud.mouth_open
        drain(quiet)
        drain(loud)
    finally:
        quiet.stop()
        loud.stop()


def test_gain_does_not_wrap_on_clipping():
    """Scaling past full scale must clamp, not wrap around to -32768."""
    player = SpeechPlayer(NullSink(), frame_ms=20, gain=8.0)
    player.start()
    try:
        player.feed(tone(0.2, amplitude=0.9))
        time.sleep(0.1)
        assert player.mouth_open > 0.8
        drain(player)
    finally:
        player.stop()


def test_wav_sink_writes_a_valid_file(tmp_path):
    import wave

    path = tmp_path / "out.wav"
    player = SpeechPlayer(WavSink(str(path)), frame_ms=20)
    player.start()
    try:
        player.feed(tone(0.4))
        drain(player)
    finally:
        player.stop()

    with wave.open(str(path)) as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == OUTPUT_SAMPLE_RATE
        assert handle.getnframes() > 0


def test_lipsync_delay_shifts_the_mouth_later():
    player = SpeechPlayer(NullSink(), frame_ms=20, lipsync_delay_ms=200)
    player.start()
    try:
        player.feed(tone(1.0))
        time.sleep(0.06)
        early = player.mouth_open
        time.sleep(0.35)
        later = player.mouth_open
        assert early == 0.0, "delayed lipsync should not open the mouth immediately"
        assert later > 0.5
        drain(player)
    finally:
        player.stop()


def test_feeding_empty_audio_is_a_no_op():
    player = SpeechPlayer(NullSink(), frame_ms=20)
    player.start()
    try:
        player.feed(b"")
        time.sleep(0.05)
        assert player.pending_bytes == 0
        assert player.mouth_open == 0.0
    finally:
        player.stop()


def test_stop_is_idempotent():
    player = SpeechPlayer(NullSink(), frame_ms=20)
    player.start()
    player.stop()
    player.stop()
