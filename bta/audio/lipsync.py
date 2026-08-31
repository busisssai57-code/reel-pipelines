"""Turn PCM frames into mouth-parameter values.

VTube Studio's API has no audio input — it only accepts numeric parameter
values — so lip sync has to be derived here and injected as parameters. We
compute a loudness envelope per audio frame and shape it with attack/release
smoothing so the mouth opens fast on an onset and closes gently, which reads
much more naturally than raw amplitude.
"""

from __future__ import annotations

import array
import math

# Loudness range mapped onto a fully closed / fully open mouth. Speech from the
# Live API sits roughly between these, with silence well below the floor.
FLOOR_DB = -48.0
CEIL_DB = -12.0

# Below this the mouth is snapped shut. An exponential release only approaches
# zero asymptotically, and a mouth stuck at 0.004 is both invisible and enough
# to keep the avatar loop injecting forever, which would stop VTube Studio's
# own face tracking from ever taking the model back.
CLOSED_THRESHOLD = 0.01


def frame_rms_db(pcm: bytes) -> float:
    """RMS of a 16-bit LE mono frame, in dBFS. Silence returns -inf."""
    if len(pcm) < 2:
        return -math.inf
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if not samples:
        return -math.inf
    total = 0
    for sample in samples:
        total += sample * sample
    rms = math.sqrt(total / len(samples)) / 32768.0
    if rms <= 1e-9:
        return -math.inf
    return 20.0 * math.log10(rms)


class LipSyncAnalyzer:
    """Stateful envelope follower producing mouth open/form values in [0, 1]."""

    def __init__(
        self,
        *,
        frame_ms: int = 20,
        attack_ms: float = 25.0,
        release_ms: float = 90.0,
        floor_db: float = FLOOR_DB,
        ceil_db: float = CEIL_DB,
        openness: float = 1.0,
    ) -> None:
        self.frame_ms = max(1, frame_ms)
        self.floor_db = floor_db
        self.ceil_db = ceil_db
        self.openness = openness
        self._attack = self._coefficient(attack_ms)
        self._release = self._coefficient(release_ms)
        self.mouth_open = 0.0
        self.mouth_form = 0.0

    def _coefficient(self, time_constant_ms: float) -> float:
        """One-pole smoothing coefficient for this frame size."""
        if time_constant_ms <= 0:
            return 1.0
        return 1.0 - math.exp(-self.frame_ms / time_constant_ms)

    def _target_from_db(self, db: float) -> float:
        if db == -math.inf or db <= self.floor_db:
            return 0.0
        span = self.ceil_db - self.floor_db
        if span <= 0:
            return 1.0
        normalized = (db - self.floor_db) / span
        return min(1.0, max(0.0, normalized))

    def feed(self, pcm: bytes) -> float:
        """Advance the envelope by one frame; returns the new mouth_open."""
        return self._advance(self._target_from_db(frame_rms_db(pcm)))

    def decay(self) -> float:
        """Advance one frame of silence (no audio available)."""
        return self._advance(0.0)

    def _advance(self, target: float) -> float:
        # Perceptual curve: linear loudness looks too "twitchy" on a model.
        target = target**0.65
        coefficient = self._attack if target > self.mouth_open else self._release
        self.mouth_open += (target - self.mouth_open) * coefficient
        if self.mouth_open < CLOSED_THRESHOLD:
            self.mouth_open = 0.0
        self.mouth_open = min(1.0, self.mouth_open * self.openness)
        # Wide vowels read as a slightly wider mouth shape; keeps the face alive
        # without pretending we have real viseme classification.
        self.mouth_form += (self.mouth_open * 0.5 - self.mouth_form) * self._release
        if self.mouth_open == 0.0 and self.mouth_form < CLOSED_THRESHOLD:
            self.mouth_form = 0.0
        return self.mouth_open

    def reset(self) -> None:
        self.mouth_open = 0.0
        self.mouth_form = 0.0
