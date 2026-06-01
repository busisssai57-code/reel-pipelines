"""Title + thumbnail variant system (takeaway #2, MrBeast formula).

Generates N packaging variants per reel following "one face, one object, one
question" with a big number/stake. Titles come from qwen (offline fallback
included); the thumbnail image is composited over a frame of the reel with
FFmpeg drawtext. Variants are meant to be A/B-tested: the audience-feedback ->
priors loop selects winners (CTR signal is [FILL: analytics source]).
"""
from __future__ import annotations
import logging
from pathlib import Path
from . import config, qwen_client, ffmpeg_build

log = logging.getLogger("thumbnails")

# big bold font for the MrBeast-style number; falls back if absent
_WIN_FONT = r"C\:/Windows/Fonts/arialbd.ttf"


def title_variants(topic: str, title: str, n: int = 4) -> list[dict]:
    """Return [{title, big_number, object}] packaging variants."""
    return qwen_client.thumbnail_titles(topic or title, title, n)


def make_thumbnail(video: Path, title: str, out: Path, *, big_number: str | None = None,
                   at: float = 1.0) -> Path | None:
    """Composite a thumbnail from a frame of `video` with title + big number overlay.

    Returns the path, or None if FFmpeg is unavailable (degrade gracefully).
    """
    video, out = Path(video), Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    title_txt = (title or "").replace(":", "\\:").replace("'", "")[:40]
    filters = [
        f"drawtext=fontfile='{_WIN_FONT}':text='{title_txt}':fontcolor=white:fontsize=72:"
        "borderw=6:bordercolor=black:x=(w-text_w)/2:y=h-280:box=1:boxcolor=black@0.35:boxborderw=20",
    ]
    if big_number:
        num = big_number.replace(":", "").replace("'", "")[:8]
        filters.append(
            f"drawtext=fontfile='{_WIN_FONT}':text='{num}':fontcolor=yellow:fontsize=180:"
            "borderw=10:bordercolor=black:x=(w-text_w)/2:y=160")
    try:
        ffmpeg_build._run(["-ss", f"{at:.2f}", "-i", str(video), "-vframes", "1",
                           "-vf", ",".join(filters), "-q:v", "3", str(out)])
        return out
    except ffmpeg_build.FFmpegMissing:
        log.warning("FFmpeg missing; thumbnail image skipped (titles still generated)")
        return None
    except Exception as e:
        log.warning("thumbnail compositing failed: %s", e)
        return None


def generate_variants(draft: dict, n: int = 3) -> list[dict]:
    """Produce N packaging variants (title + optional thumbnail image) for a draft."""
    variants = title_variants(draft.get("topic", ""), draft.get("title", ""), n)
    video = draft.get("video_path")
    out = []
    for i, v in enumerate(variants):
        thumb = None
        if video and Path(video).exists():
            thumb = make_thumbnail(video, v["title"],
                                   Path(video).with_name(f"{Path(video).stem}_v{i}.jpg"),
                                   big_number=v.get("big_number"))
        out.append({**v, "thumbnail": str(thumb) if thumb else None})
    return out
