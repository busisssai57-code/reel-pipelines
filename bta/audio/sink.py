"""Where the model's speech actually goes."""

from __future__ import annotations

import contextlib
import wave
from pathlib import Path
from typing import Protocol

from bta.config import CHANNELS, OUTPUT_SAMPLE_RATE, SAMPLE_WIDTH, AudioConfig
from bta.log import get_logger

log = get_logger("audio.sink")


class AudioSink(Protocol):
    """Accepts 16-bit LE mono PCM frames at OUTPUT_SAMPLE_RATE."""

    name: str

    def write(self, pcm: bytes) -> None: ...

    def flush(self) -> None:
        """Drop anything buffered but not yet played (barge-in)."""

    def close(self) -> None: ...


class NullSink:
    """Discards audio. Used for headless runs and tests."""

    name = "null"

    def __init__(self) -> None:
        self.bytes_written = 0

    def write(self, pcm: bytes) -> None:
        self.bytes_written += len(pcm)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class WavSink:
    """Appends every frame to a .wav file. Useful for verifying output offline."""

    name = "wav"

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._wave = wave.open(str(self.path), "wb")
        self._wave.setnchannels(CHANNELS)
        self._wave.setsampwidth(SAMPLE_WIDTH)
        self._wave.setframerate(OUTPUT_SAMPLE_RATE)
        self.bytes_written = 0

    def write(self, pcm: bytes) -> None:
        self._wave.writeframes(pcm)
        self.bytes_written += len(pcm)

    def flush(self) -> None:
        pass  # Already-written frames stay in the file by design.

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._wave.close()


class DeviceSink:
    """Plays audio through a sound device via sounddevice/PortAudio.

    Point this at a virtual cable (VB-Audio, BlackHole, PulseAudio null sink)
    so OBS picks the voice up as an input.
    """

    name = "device"

    def __init__(self, device: str = "") -> None:
        import sounddevice  # imported lazily: PortAudio may not be installed

        self._sd = sounddevice
        selected: str | int | None = device or None
        if isinstance(selected, str) and selected.isdigit():
            selected = int(selected)

        self._stream = sounddevice.RawOutputStream(
            samplerate=OUTPUT_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            device=selected,
            blocksize=0,
            latency="low",
        )
        self._stream.start()
        self.bytes_written = 0
        log.info("Audio device open: %s", self._stream.device)

    def write(self, pcm: bytes) -> None:
        self._stream.write(pcm)
        self.bytes_written += len(pcm)

    def flush(self) -> None:
        # Restarting the stream is the only way PortAudio lets us drop the
        # frames already handed to the driver.
        with contextlib.suppress(Exception):
            self._stream.stop()
            self._stream.start()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._stream.stop()
            self._stream.close()

    @staticmethod
    def list_devices() -> str:
        import sounddevice

        return str(sounddevice.query_devices())


def build_sink(cfg: AudioConfig) -> AudioSink:
    """Build the configured sink, degrading to a usable one rather than dying."""
    if cfg.sink == "null":
        return NullSink()
    if cfg.sink == "wav":
        return WavSink(cfg.wav_path)

    try:
        return DeviceSink(cfg.device)
    except Exception as exc:  # PortAudio missing, no output device, bad name
        log.warning(
            "Audio device unavailable (%s); falling back to WAV file at %s",
            exc,
            cfg.wav_path,
        )
        try:
            return WavSink(cfg.wav_path)
        except Exception as wav_exc:
            log.warning("WAV sink unavailable (%s); audio will be discarded", wav_exc)
            return NullSink()
