"""Lip-sync envelope behaviour."""

from __future__ import annotations

import math

from conftest import silence, tone

from bta.audio.lipsync import LipSyncAnalyzer, frame_rms_db


def frames(pcm: bytes, frame_ms: int = 20, rate: int = 24_000) -> list[bytes]:
    size = rate * 2 * frame_ms // 1000
    return [pcm[i : i + size] for i in range(0, len(pcm) - size + 1, size)]


def test_rms_db_of_silence_is_negative_infinity():
    assert frame_rms_db(silence(0.02)) == -math.inf


def test_rms_db_tracks_amplitude():
    loud = frame_rms_db(tone(0.02, amplitude=0.9))
    quiet = frame_rms_db(tone(0.02, amplitude=0.05))
    assert loud > quiet
    # A 0.9-amplitude sine has RMS 0.9/sqrt(2) = 0.636, i.e. about -3.9 dBFS.
    assert -3.0 > loud > -5.0
    assert quiet < -20.0


def test_rms_db_handles_short_and_odd_input():
    assert frame_rms_db(b"") == -math.inf
    assert frame_rms_db(b"\x01") == -math.inf  # half a sample, no crash


def test_mouth_opens_on_speech_and_closes_on_silence():
    analyzer = LipSyncAnalyzer(frame_ms=20)
    for frame in frames(tone(0.4)):
        analyzer.feed(frame)
    opened = analyzer.mouth_open
    assert opened > 0.7, f"mouth should open on loud audio, got {opened}"

    for frame in frames(silence(0.5)):
        analyzer.feed(frame)
    assert analyzer.mouth_open == 0.0, "mouth should fully close on silence"


def test_values_stay_in_range_across_amplitudes():
    analyzer = LipSyncAnalyzer(frame_ms=20)
    for amplitude in (0.0, 0.01, 0.3, 1.0, 0.5):
        for frame in frames(tone(0.2, amplitude=amplitude) if amplitude else silence(0.2)):
            value = analyzer.feed(frame)
            assert 0.0 <= value <= 1.0
            assert 0.0 <= analyzer.mouth_form <= 1.0


def test_attack_is_faster_than_release():
    """The mouth should snap open and fall shut more gently."""
    analyzer = LipSyncAnalyzer(frame_ms=20)
    loud = frames(tone(0.1))[0]

    analyzer.feed(loud)
    after_one_loud_frame = analyzer.mouth_open

    for frame in frames(tone(0.4)):
        analyzer.feed(frame)
    steady = analyzer.mouth_open
    analyzer.feed(silence(0.02))
    dropped = steady - analyzer.mouth_open

    assert after_one_loud_frame > dropped, "attack should outpace release"


def test_decay_closes_mouth_without_audio():
    analyzer = LipSyncAnalyzer(frame_ms=20)
    for frame in frames(tone(0.3)):
        analyzer.feed(frame)
    assert analyzer.mouth_open > 0
    for _ in range(200):
        analyzer.decay()
    assert analyzer.mouth_open == 0.0


def test_reset_clears_state():
    analyzer = LipSyncAnalyzer(frame_ms=20)
    for frame in frames(tone(0.3)):
        analyzer.feed(frame)
    analyzer.reset()
    assert analyzer.mouth_open == 0.0
    assert analyzer.mouth_form == 0.0
