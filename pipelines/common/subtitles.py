"""Build category-styled .ass subtitles from Whisper word timestamps.

Words are grouped into short phrases (max ~4 words / ~2.2s) and rendered with a
karaoke-style highlight on the active word. Styling is driven by config.SUBTITLE_STYLES.
"""
from __future__ import annotations
from pathlib import Path
from . import config

MAX_WORDS = 4
MAX_DUR = 2.2


def _ts(t: float) -> str:
    if t < 0:
        t = 0
    h = int(t // 3600); t -= h * 3600
    m = int(t // 60); t -= m * 60
    s = int(t); cs = int(round((t - s) * 100))
    if cs == 100:
        cs = 0; s += 1
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _group(words: list[dict]) -> list[list[dict]]:
    groups, cur = [], []
    for w in words:
        if not cur:
            cur = [w]; continue
        span = w["end"] - cur[0]["start"]
        if len(cur) >= MAX_WORDS or span > MAX_DUR:
            groups.append(cur); cur = [w]
        else:
            cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def build_ass(words: list[dict], category: str, out_path: Path) -> Path:
    out_path = Path(out_path)
    st = config.style_for(category)
    # ASS Alignment 5 = centered middle. We nudge with MarginV.
    margin_v = int(config.HEIGHT * 0.18)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {config.WIDTH}
PlayResY: {config.HEIGHT}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{st['font']},{st['size']},{st['primary']},{st['highlight']},{st['outline']},&H64000000,-1,0,0,0,100,100,0,0,1,{st['outline_px']},3,2,80,80,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for grp in _group(words):
        start, end = grp[0]["start"], grp[-1]["end"]
        # karaoke: \k duration in centiseconds; active word takes highlight (SecondaryColour)
        text = ""
        for w in grp:
            kcs = max(1, int(round((w["end"] - w["start"]) * 100)))
            token = w["word"].replace("{", "(").replace("}", ")")
            text += f"{{\\kf{kcs}}}{token} "
        lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Main,,0,0,0,,{text.strip()}")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
