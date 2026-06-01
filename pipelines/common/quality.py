"""Production quality gates and autofixes for reel outputs.

The goal is not to claim subjective perfection. These gates enforce measurable
signals that matter for high-retention creator videos: immediate hook, strong
title, tight pacing, enough visual beats, valid export specs, and traceability.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from . import config, ffmpeg_build


POWER_WORDS = {
    "secret", "surprising", "hidden", "truth", "why", "how", "never",
    "biggest", "fastest", "impossible", "tested", "mistake", "challenge",
}


def autofix_script_spec(spec: dict, topic: str, *, min_beats: int = 5) -> dict:
    """Make a script spec structurally shippable before expensive rendering."""
    spec = dict(spec)
    title = (spec.get("title") or topic or "Untitled").strip()
    if len(title) < 18 or not any(w in title.lower() for w in POWER_WORDS):
        title = f"The Hidden Truth About {title}".strip()
    spec["title"] = title[:72]

    beats = [dict(b) for b in spec.get("beats", []) if (b.get("text") or "").strip()]
    if not beats and spec.get("full_script"):
        beats = [{"text": s.strip(), "image_prompt": f"cinematic vertical shot of {topic}"}
                 for s in re.split(r"(?<=[.!?])\s+", spec["full_script"]) if s.strip()]
    if not beats:
        beats = [
            {"text": f"Stop scrolling: {topic} has one detail almost everyone misses.",
             "image_prompt": f"dramatic macro reveal of {topic}, premium documentary lighting"},
            {"text": "It looks simple at first, but the setup is doing the real work.",
             "image_prompt": f"wide cinematic setup for {topic}, high contrast"},
            {"text": "Then one decision flips the entire story.",
             "image_prompt": f"tense turning point about {topic}, neon rim light"},
            {"text": "That is the moment the audience needs to see again.",
             "image_prompt": f"slow-motion impact scene about {topic}, crisp detail"},
            {"text": "And it changes what you should do next.",
             "image_prompt": f"hero ending frame about {topic}, clean negative space"},
        ]

    while len(beats) < min_beats:
        i = len(beats) + 1
        beats.append({
            "text": f"Beat {i}: raise the stakes with a concrete visual payoff.",
            "image_prompt": f"premium vertical b-roll payoff for {topic}, beat {i}",
        })

    i = 0
    while _word_count(" ".join(b["text"] for b in beats)) < 75 and i < len(beats):
        beats[i]["text"] = (
            beats[i]["text"].rstrip(".")
            + ", then show the audience exactly why it matters with one clear visual proof."
        )
        i += 1

    if not _has_hook(_opening_words(beats[0]["text"])):
        beats[0]["text"] = f"Stop scrolling: {beats[0]['text']}"

    spec["beats"] = beats[:8]
    spec["full_script"] = " ".join(b["text"].strip() for b in spec["beats"])
    spec.setdefault("category", "default")
    spec.setdefault("mood", "documentary")
    return spec


def score_script_spec(spec: dict) -> dict:
    beats = spec.get("beats", [])
    script = spec.get("full_script") or " ".join(b.get("text", "") for b in beats)
    words = re.findall(r"\w+", script)
    title = spec.get("title", "")
    checks = {
        "hook_first_8_words": _has_hook(" ".join(words[:8])) if words else False,
        "title_power": any(w in title.lower() for w in POWER_WORDS),
        "beat_count": 5 <= len(beats) <= 8,
        "word_count": 75 <= len(words) <= 180,
        "visual_prompts": all((b.get("image_prompt") or "").strip() for b in beats),
        "no_unverified_superlatives": not re.search(r"\b(world'?s|guaranteed|proven|#1)\b", script, re.I),
    }
    passed = sum(1 for ok in checks.values() if ok)
    return {
        "score": round(passed / len(checks), 3),
        "passed": passed == len(checks),
        "checks": checks,
        "word_count": len(words),
        "beat_count": len(beats),
    }


def validate_export(video_path: Path, workflow_path: Path | None = None) -> dict:
    video_path = Path(video_path)
    checks = {
        "exists": video_path.exists(),
        "duration_ok": False,
        "resolution_ok": False,
        "audio_present": False,
        "workflow_card": bool(workflow_path and Path(workflow_path).exists()),
    }
    info = {"duration": 0.0, "width": 0, "height": 0, "fps": 0.0}
    if video_path.exists():
        info.update(_probe_video(video_path))
        checks["duration_ok"] = 8 <= info["duration"] <= 180
        checks["resolution_ok"] = info["width"] == config.WIDTH and info["height"] == config.HEIGHT
        checks["audio_present"] = _has_audio(video_path)
    passed = sum(1 for ok in checks.values() if ok)
    return {
        "score": round(passed / len(checks), 3),
        "passed": passed == len(checks),
        "checks": checks,
        **info,
    }


def write_quality_report(video_path: Path, script_report: dict, export_report: dict) -> Path:
    report = {
        "video": str(video_path),
        "script": script_report,
        "export": export_report,
        "passed": script_report.get("passed") and export_report.get("passed"),
    }
    out = Path(video_path).with_suffix(".quality.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out


def _has_hook(text: str) -> bool:
    text = text.lower()
    return any(token in text for token in (
        "stop", "why", "how", "secret", "hidden", "truth", "never",
        "surprising", "biggest", "tested", "challenge", "?",
    ))


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))


def _opening_words(text: str, n: int = 8) -> str:
    return " ".join(re.findall(r"\w+", text)[:n])


def _probe_video(path: Path) -> dict:
    try:
        p = subprocess.run([
            config.FFPROBE, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate", "-show_entries", "format=duration",
            "-of", "json", str(path)
        ], capture_output=True, text=True)
        data = json.loads(p.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        fps_raw = stream.get("r_frame_rate", "0/1")
        num, den = [float(x) for x in fps_raw.split("/")]
        return {
            "duration": float((data.get("format") or {}).get("duration") or 0),
            "width": int(stream.get("width") or 0),
            "height": int(stream.get("height") or 0),
            "fps": round(num / den, 3) if den else 0.0,
        }
    except Exception:
        return {"duration": ffmpeg_build.probe_duration(path), "width": 0, "height": 0, "fps": 0.0}


def _has_audio(path: Path) -> bool:
    try:
        p = subprocess.run([
            config.FFPROBE, "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_type", "-of", "json", str(path)
        ], capture_output=True, text=True)
        data = json.loads(p.stdout or "{}")
        return bool(data.get("streams"))
    except Exception:
        return False


def visual_qa(video: Path, target_dur: float) -> tuple[bool, str]:
    """Pass if the export exists and its duration is within 15% of the voiceover.

    Extracted from pipeline_a/pipeline_b to avoid duplication.
    """
    if not Path(video).exists():
        return False, "no output file"
    d = ffmpeg_build.probe_duration(video)
    if d <= 0.5:
        return False, "zero-length output"
    if target_dur and abs(d - target_dur) / target_dur > 0.15:
        return False, f"duration {d:.1f}s off target {target_dur:.1f}s"
    return True, f"ok ({d:.1f}s)"
