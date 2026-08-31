"""Real-time speech playback with lip-sync derived from the same frames.

The player owns a dedicated thread because sink writes are blocking I/O. It
pulls fixed-size frames out of a buffer, hands each one to the sink and to the
lip-sync analyzer in the same step, so the mouth value always describes the
audio being played right now rather than audio that arrived from the network
seconds ahead of schedule.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from bta.audio.lipsync import LipSyncAnalyzer
from bta.audio.sink import AudioSink
from bta.config import CHANNELS, OUTPUT_SAMPLE_RATE, SAMPLE_WIDTH
from bta.log import get_logger

log = get_logger("audio.player")


def _apply_gain(pcm: bytes, gain: float) -> bytes:
    if gain == 1.0:
        return pcm
    import array

    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    for i, sample in enumerate(samples):
        scaled = int(sample * gain)
        samples[i] = 32767 if scaled > 32767 else (-32768 if scaled < -32768 else scaled)
    return samples.tobytes()


class SpeechPlayer:
    """Buffers model audio, plays it at real time, and exposes mouth values."""

    def __init__(
        self,
        sink: AudioSink,
        *,
        frame_ms: int = 20,
        gain: float = 1.0,
        lipsync_delay_ms: int = 0,
    ) -> None:
        self.sink = sink
        self.frame_ms = max(1, frame_ms)
        self.gain = gain
        self.frame_bytes = (
            OUTPUT_SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS * self.frame_ms
        ) // 1000
        self.analyzer = LipSyncAnalyzer(frame_ms=self.frame_ms)

        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        # Mouth values are published one frame at a time; the delay line lets a
        # user compensate for buffering between us and what the viewer hears.
        delay_frames = max(0, lipsync_delay_ms // self.frame_ms)
        self._delay_line: deque[tuple[float, float]] = deque(
            [(0.0, 0.0)] * delay_frames, maxlen=delay_frames + 1
        )
        self._delay_frames = delay_frames

        self.mouth_open = 0.0
        self.mouth_form = 0.0
        self.speaking = False
        self.frames_played = 0

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._pump, name="speech-player", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)
        self.sink.close()

    # -- producer side (async) ---------------------------------------------

    def feed(self, pcm: bytes) -> None:
        """Queue model audio for playback. Safe to call from the event loop."""
        if not pcm:
            return
        with self._lock:
            self._buffer.extend(_apply_gain(pcm, self.gain))
        self._wake.set()

    def interrupt(self) -> None:
        """Drop pending audio — the model was cut off mid-sentence."""
        with self._lock:
            dropped = len(self._buffer)
            self._buffer.clear()
        if dropped:
            log.debug("Interrupted, dropped %d bytes of pending audio", dropped)
        self.sink.flush()
        # The sound stops instantly, so the mouth has to as well. Letting the
        # envelope glide down would leave the avatar mouthing silently for a
        # few hundred milliseconds after it was cut off.
        self.analyzer.reset()
        self._delay_line.clear()
        self._delay_line.extend([(0.0, 0.0)] * self._delay_frames)
        self.mouth_open = 0.0
        self.mouth_form = 0.0
        self.speaking = False

    @property
    def pending_bytes(self) -> int:
        with self._lock:
            return len(self._buffer)

    @property
    def pending_seconds(self) -> float:
        return self.pending_bytes / (OUTPUT_SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS)

    # -- consumer side (player thread) -------------------------------------

    def _take_frame(self) -> bytes | None:
        with self._lock:
            if len(self._buffer) < self.frame_bytes:
                return None
            frame = bytes(self._buffer[: self.frame_bytes])
            del self._buffer[: self.frame_bytes]
            return frame

    def _publish(self, open_value: float, form_value: float) -> None:
        if self._delay_frames:
            self._delay_line.append((open_value, form_value))
            open_value, form_value = self._delay_line[0]
        self.mouth_open = open_value
        self.mouth_form = form_value

    def _pump(self) -> None:
        frame_seconds = self.frame_ms / 1000.0
        deadline = time.monotonic()
        while not self._stop.is_set():
            frame = self._take_frame()
            if frame is None:
                # Silence: let the mouth close, then idle until audio arrives.
                self.speaking = False
                if self.analyzer.mouth_open > 0.0 or self._delay_frames:
                    self.analyzer.decay()
                    self._publish(self.analyzer.mouth_open, self.analyzer.mouth_form)
                    time.sleep(frame_seconds)
                else:
                    self._publish(0.0, 0.0)
                    self._wake.wait(timeout=0.1)
                    self._wake.clear()
                deadline = time.monotonic()
                continue

            self.speaking = True
            try:
                self.sink.write(frame)
            except Exception:
                log.exception("Audio sink write failed; dropping frame")
            self.analyzer.feed(frame)
            self._publish(self.analyzer.mouth_open, self.analyzer.mouth_form)
            self.frames_played += 1

            # A device sink blocks in write() and paces itself. Everything else
            # would run flat out, so hold it to real time here.
            deadline += frame_seconds
            if getattr(self.sink, "name", "") != "device":
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
                elif remaining < -frame_seconds * 5:
                    deadline = time.monotonic()  # fell far behind; resync
