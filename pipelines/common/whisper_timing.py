"""Whisper word-level timestamps from the voiceover WAV.

Prefers faster-whisper; falls back to openai-whisper; if neither is present,
evenly distributes word timings across the audio duration so subtitles still
render in sync for testing.
"""
from __future__ import annotations
import logging, wave
from pathlib import Path
from . import config

log = logging.getLogger("whisper")
_model = None


def _audio_duration(wav: Path) -> float:
    with wave.open(str(wav), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def transcribe_words(wav: Path, script_text: str = "", model_size: str = "base") -> list[dict]:
    """Return [{word, start, end}, ...] in seconds."""
    wav = Path(wav)
    # 1) faster-whisper
    try:
        from faster_whisper import WhisperModel
        global _model
        if _model is None:
            _model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, _ = _model.transcribe(str(wav), word_timestamps=True)
        words = []
        for seg in segments:
            for w in (seg.words or []):
                words.append({"word": w.word.strip(), "start": w.start, "end": w.end})
        if words:
            log.info("faster-whisper: %d words", len(words))
            return words
    except Exception as e:
        log.warning("faster-whisper unavailable (%s)", e)

    # 2) openai-whisper
    try:
        import whisper
        m = whisper.load_model(model_size)
        res = m.transcribe(str(wav), word_timestamps=True)
        words = []
        for seg in res.get("segments", []):
            for w in seg.get("words", []):
                words.append({"word": w["word"].strip(),
                              "start": w["start"], "end": w["end"]})
        if words:
            log.info("openai-whisper: %d words", len(words))
            return words
    except Exception as e:
        log.warning("openai-whisper unavailable (%s)", e)

    # 3) even-distribution fallback from the known script
    log.warning("Falling back to even-distribution timing")
    dur = _audio_duration(wav)
    toks = (script_text or "narration").split()
    if not toks:
        return []
    step = dur / len(toks)
    return [{"word": t, "start": i * step, "end": (i + 1) * step}
            for i, t in enumerate(toks)]
