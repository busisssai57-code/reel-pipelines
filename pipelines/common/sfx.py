"""Offline sound-effect library, synthesized with FFmpeg (no external assets).

The AudioEditorAgent uses these to punch up a finished reel: a riser on the
hook, a whoosh on each scene transition, a ding on the closer. Everything is
generated procedurally via ffmpeg `lavfi` so the system stays fully offline and
license-clean. Files are cached under pipelines/common/assets/sfx/.
"""
from __future__ import annotations
import logging
from pathlib import Path
from . import config

log = logging.getLogger("sfx")
SFX_DIR = Path(__file__).resolve().parent / "assets" / "sfx"

# name -> lavfi source expression producing ~mono audio; trimmed/faded on synth.
_RECIPES: dict[str, dict] = {
    # short upward sweep to lift into the hook
    "riser":  {"src": "aevalsrc='0.5*sin(2*PI*t*(220+700*t))':d=1.1:s=48000",
               "dur": 1.1, "fade_in": 0.05, "fade_out": 0.25},
    # airy noise sweep for cuts between scenes
    "whoosh": {"src": "anoisesrc=d=0.45:c=pink:a=0.6,bandpass=f=1200:width_type=h:w=1600",
               "dur": 0.45, "fade_in": 0.04, "fade_out": 0.25},
    # bright confirmation tone for the closing beat
    "ding":   {"src": "sine=frequency=880:duration=0.6:sample_rate=48000",
               "dur": 0.6, "fade_in": 0.005, "fade_out": 0.45},
    # soft pop to accent a key word/number
    "pop":    {"src": "sine=frequency=320:duration=0.14:sample_rate=48000",
               "dur": 0.14, "fade_in": 0.003, "fade_out": 0.1},
}


def _synth_one(name: str, recipe: dict) -> Path:
    from . import ffmpeg_build  # local import to avoid cycle at module load
    out = SFX_DIR / f"{name}.wav"
    fi, fo, dur = recipe["fade_in"], recipe["fade_out"], recipe["dur"]
    af = f"afade=t=in:st=0:d={fi},afade=t=out:st={max(0.0, dur-fo):.3f}:d={fo}"
    ffmpeg_build._run([
        "-f", "lavfi", "-i", recipe["src"],
        "-af", af, "-ac", "1", "-ar", "48000", "-t", f"{dur:.3f}", out,
    ])
    return out


def ensure_library() -> dict[str, Path]:
    """Synthesize any missing SFX and return {name: path}. Safe to call often."""
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name, recipe in _RECIPES.items():
        p = SFX_DIR / f"{name}.wav"
        if not p.exists() or p.stat().st_size == 0:
            try:
                _synth_one(name, recipe)
            except Exception as e:
                log.warning("SFX synth failed for %s: %s", name, e)
                continue
        if p.exists():
            paths[name] = p
    return paths


def plan_cues(duration: float, n_beats: int = 0) -> list[dict]:
    """Build a default cue list for a reel of `duration` seconds.

    riser at the hook, whoosh at evenly spaced transitions, ding on the closer.
    Returns [{t, sfx, gain}] where gain is a linear multiplier.
    """
    if duration <= 0:
        return []
    cues: list[dict] = [{"t": 0.15, "sfx": "riser", "gain": 0.5}]
    transitions = max(2, (n_beats - 1) if n_beats else 3)
    for i in range(1, transitions):
        t = duration * i / transitions
        if 0.5 < t < duration - 0.8:
            cues.append({"t": round(t, 2), "sfx": "whoosh", "gain": 0.45})
    cues.append({"t": max(0.0, duration - 0.6), "sfx": "ding", "gain": 0.5})
    return cues
