"""Local Kokoro TTS. Renders narration to WAV; supports round-robin voice rotation.

Falls back to a silent-but-correctly-timed WAV (approx 15 chars/sec) if Kokoro
is not installed, so downstream stages remain testable.
"""
from __future__ import annotations
import logging, wave, struct
from pathlib import Path
import numpy as np
from . import config, db

log = logging.getLogger("kokoro")
SAMPLE_RATE = 24000
_pipelines: dict[str, "KPipeline"] = {}


def _get_pipeline(lang_code: str = "a"):
    """Lazily load and cache Kokoro model per language code."""
    global _pipelines
    if lang_code not in _pipelines:
        from kokoro import KPipeline  # lazy import
        _pipelines[lang_code] = KPipeline(lang_code=lang_code)
    return _pipelines[lang_code]


def pick_voice(rotate: bool, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    if not rotate:
        return config.VOICE_POOL[0]
    idx = db.next_voice_index(len(config.VOICE_POOL))
    return config.VOICE_POOL[idx]


def _lang_for_voice(voice: str) -> str:
    return "b" if voice.startswith(("bf_", "bm_")) else "a"


def synthesize(text: str, out_wav: Path, rotate: bool = False,
               voice: str | None = None) -> tuple[Path, str]:
    """Render `text` to `out_wav`. Returns (path, voice_used)."""
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    chosen = pick_voice(rotate, voice)
    try:
        lang_code = _lang_for_voice(chosen)
        pipe = _get_pipeline(lang_code)
        chunks = []
        for _, _, audio in pipe(text, voice=chosen, speed=1.0):
            chunks.append(np.asarray(audio, dtype=np.float32))
        audio = np.concatenate(chunks) if chunks else np.zeros(SAMPLE_RATE, np.float32)
        _write_wav(out_wav, audio, SAMPLE_RATE)
        log.info("Kokoro rendered %.1fs with voice=%s", len(audio) / SAMPLE_RATE, chosen)
    except Exception as e:
        log.warning("Kokoro unavailable (%s); writing placeholder silence", e)
        dur = max(2.0, len(text) / 15.0)
        audio = np.zeros(int(dur * SAMPLE_RATE), np.float32)
        _write_wav(out_wav, audio, SAMPLE_RATE)
    return out_wav, chosen


def _write_wav(path: Path, audio: np.ndarray, sr: int):
    audio = np.clip(audio, -1.0, 1.0)
    pcm = (audio * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
