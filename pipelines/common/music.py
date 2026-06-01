"""Topic-matched music: pick a free/CC track from the local library by mood.

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
        log.warning("music_library is empty; reel will export without music")
        return None
    keys = config.MOOD_KEYWORDS.get((mood or "").lower(), [])
    matches = [t for t in tracks if any(k in t.stem.lower() for k in keys)]
    chosen = random.choice(matches) if matches else random.choice(tracks)
    log.info("music: mood=%s -> %s", mood, chosen.name)
    return chosen
