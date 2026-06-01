"""Topic-matched music: pick a free/CC track or generate a local music bed.

Drop CC0 / Creative-Commons tracks into  music_library/  with descriptive names
(e.g. epic_cinematic_01.mp3, calm_ambient_forest.mp3). Selection matches the
mood keyword; loudness normalization + ducking happen in ffmpeg_build.
"""
from __future__ import annotations
import logging, random
from pathlib import Path
from . import config

log = logging.getLogger("music")
EXTS = (".mp3", ".wav", ".m4a", ".ogg", ".flac")


def pick_track(mood: str) -> Path | None:
    lib = list(config.MUSIC_LIBRARY.glob("*"))
    tracks = [p for p in lib if p.suffix.lower() in EXTS]
    if not tracks:
        log.warning("music_library is empty; generating local procedural music bed")
        return _procedural_bed(mood)
    keys = config.MOOD_KEYWORDS.get((mood or "").lower(), [])
    matches = [t for t in tracks if any(k in t.stem.lower() for k in keys)]
    chosen = random.choice(matches) if matches else random.choice(tracks)
    log.info("music: mood=%s -> %s", mood, chosen.name)
    return chosen


def _procedural_bed(mood: str) -> Path | None:
    """Generate a reusable, royalty-free ambient bed fully offline."""
    try:
        from . import ffmpeg_build

        mood = (mood or "documentary").lower()
        freqs = {
            "epic": (55, 110, 220),
            "mysterious": (48, 96, 144),
            "uplifting": (65, 130, 260),
            "calm": (52, 104, 208),
            "documentary": (60, 120, 180),
        }.get(mood, (60, 120, 180))
        outdir = config.OUTPUT / "generated_music"
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / f"{mood}_procedural_bed.wav"
        if out.exists():
            return out
        inputs = []
        for f in freqs:
            inputs += ["-f", "lavfi", "-i", f"sine=frequency={f}:duration=180:sample_rate=48000"]
        filt = (
            "[0:a]volume=0.20,afade=t=in:st=0:d=2[a0];"
            "[1:a]volume=0.11,adelay=650|650[a1];"
            "[2:a]volume=0.08,adelay=1300|1300[a2];"
            "[a0][a1][a2]amix=inputs=3:duration=first,"
            "acompressor=threshold=0.08:ratio=3,"
            "alimiter=limit=0.80[aout]"
        )
        ffmpeg_build._run([*inputs, "-filter_complex", filt, "-map", "[aout]", out])
        return out
    except Exception as e:
        log.warning("procedural music generation failed: %s", e)
        return None
