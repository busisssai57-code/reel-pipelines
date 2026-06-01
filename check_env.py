#!/usr/bin/env python
"""Environment / dependency check for the reel pipelines."""
from __future__ import annotations
import shutil, importlib
from pathlib import Path


def _has_module(name: str) -> bool:
    try:
        importlib.import_module(name); return True
    except Exception:
        return False


def main():
    print("=== Reel Pipeline environment check ===\n")
    from pipelines.common import config
    # binaries
    for b, configured in (("ffmpeg", config.FFMPEG), ("ffprobe", config.FFPROBE)):
        path = shutil.which(configured) or (configured if Path(configured).exists() else "")
        print(f"[{'OK ' if path else 'MISS'}] {b:8} -> {path or 'NOT FOUND (run scripts/install-ffmpeg.ps1)'}")
    # python deps
    deps = {
        "openai": "qwen client", "kokoro": "Kokoro TTS",
        "faster_whisper": "Whisper timestamps", "requests": "media APIs",
        "discord": "Discord bot", "apscheduler": "scheduler",
        "dotenv": "env loading", "numpy": "audio buffers", "soundfile": "wav io",
    }
    print()
    for mod, desc in deps.items():
        print(f"[{'OK ' if _has_module(mod) else 'MISS'}] {mod:16} {desc}")
    # optional
    print()
    for mod, desc in {"torch": "local SD images", "diffusers": "local SD images",
                      "whisper": "fallback timestamps"}.items():
        print(f"[{'OK ' if _has_module(mod) else 'SKIP'}] {mod:16} (optional) {desc}")
    # keys
    print()
    for k in ("PEXELS_API_KEY", "PIXABAY_API_KEY", "DISCORD_BOT_TOKEN"):
        print(f"[{'OK ' if getattr(config, k) else 'MISS'}] {k}")
    print(f"[{'OK ' if config.DISCORD_CHANNEL_ID else 'MISS'}] DISCORD_CHANNEL_ID")
    print(f"\nqwen endpoint: {config.QWEN_BASE_URL}  model: {config.QWEN_MODEL}")
    print(f"music_library tracks: {len(list(config.MUSIC_LIBRARY.glob('*')))}")
    print()
    from pipelines.common import hunyuan_video, autopost
    h = hunyuan_video.health()
    print(f"[{'OK ' if h['available'] else 'MISS'}] Hunyuan backend -> {h['comfy_url']}")
    for name, ok in h["installed"].items():
        print(f"[{'OK ' if ok else 'MISS'}] hunyuan {name:16} {h['paths'][name]}")
    ap = autopost.status()
    print(f"[OK ] autopost mode -> {ap['mode']} (webhook={'yes' if ap['webhook_configured'] else 'no'})")
    print("\nNote: missing optional services degrade gracefully to fallbacks,")
    print("but a real final export requires configured FFmpeg binaries.")


if __name__ == "__main__":
    main()
