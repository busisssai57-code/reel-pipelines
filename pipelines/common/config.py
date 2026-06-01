"""Central config: paths, constants, per-category subtitle styles, voice rotation."""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

# ---- Paths ----
ASSETS = ROOT / "pipelines" / "common" / "assets"
OUTPUT = ROOT / "output"
DRAFTS = ROOT / "drafts"
MUSIC_LIBRARY = ROOT / "music_library"
LOGS = ROOT / "logs"
DB_PATH = ROOT / "state.db"
for _p in (ASSETS, OUTPUT, DRAFTS, MUSIC_LIBRARY, LOGS):
    _p.mkdir(parents=True, exist_ok=True)

# ---- Video format ----
WIDTH, HEIGHT, FPS = 1080, 1920, 30
VIDEO_CODEC, AUDIO_CODEC = "libx264", "aac"

# ---- Binaries ----
FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.getenv("FFPROBE_BIN", "ffprobe")

# ---- qwen (local OpenAI-compatible endpoint) ----
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "http://localhost:11434/v1")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "ollama")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen2.5:7b-instruct")

# ---- APIs ---- (support both documented and internal env var names)
PEXELS_API_KEY  = os.getenv("PEXELS_KEY")  or os.getenv("PEXELS_API_KEY",  "")
PIXABAY_API_KEY = os.getenv("PIXABAY_KEY") or os.getenv("PIXABAY_API_KEY", "")
ARCHIVE_MEDIA_ENABLED = os.getenv("ARCHIVE_MEDIA_ENABLED", "0").lower() in ("1", "true", "yes")

# ---- Discord ----
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
DRAFTS_PER_PIPELINE = int(os.getenv("DRAFTS_PER_PIPELINE", "21"))

# ---- Hunyuan Video / ComfyUI ----
COMFY_URL = os.getenv("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
COMFY_ROOT = Path(os.getenv("COMFY_ROOT", str(ROOT.parent / "ComfyUI")))
COMFY_OUTPUT = Path(os.getenv("COMFY_OUTPUT", str(COMFY_ROOT / "output")))
HUNYUAN_WORKFLOW = os.getenv(
    "HUNYUAN_WORKFLOW",
    str(ROOT / "workflows" / "hunyuan_t2v_native_api.json"),
)
HUNYUAN_MODEL = os.getenv("HUNYUAN_MODEL", "hunyuan_video_t2v_720p_bf16.safetensors")
HUNYUAN_VAE = os.getenv("HUNYUAN_VAE", "hunyuan_video_vae_bf16.safetensors")
HUNYUAN_CLIP = os.getenv("HUNYUAN_CLIP", "clip_l.safetensors")
HUNYUAN_LLM = os.getenv("HUNYUAN_LLM", "llava_llama3_fp8_scaled.safetensors")
LIPSYNC_MODEL = os.getenv("LIPSYNC_MODEL", "latentsync")

# ---- Auto-poster ----
AUTOPOST_MODE = os.getenv("AUTOPOST_MODE", "local_manifest")
AUTOPOST_WEBHOOK_URL = os.getenv("AUTOPOST_WEBHOOK_URL", "")
AUTOPOST_DRY_RUN = os.getenv("AUTOPOST_DRY_RUN", "0").lower() in ("1", "true", "yes")

# ---- Local API security ----
REEL_API_KEY = os.getenv("REEL_API_KEY", "")
CORS_ORIGIN = os.getenv("CORS_ORIGIN", "*")

# ---- YouTube OAuth (AI Team distribution) ----
YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")

# ---- TikTok API (AI Team distribution) ----
TIKTOK_CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY", "")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "")

# ---- AI Team scheduler ----
TREND_CYCLE_HOURS = int(os.getenv("TREND_CYCLE_HOURS", "24"))
ENGAGEMENT_POLL_HOURS = int(os.getenv("ENGAGEMENT_POLL_HOURS", "6"))
TREND_BATCH_SIZE = int(os.getenv("TREND_BATCH_SIZE", "3"))

# ---- AI Team autonomy (dashboard override for human control) ----
AUTO_APPROVE = os.getenv("AUTO_APPROVE", "false").lower() in ("1", "true", "yes")
AUTO_PATCH = os.getenv("AUTO_PATCH", "false").lower() in ("1", "true", "yes")

# ---- Qwen Coder (separate model for code generation) ----
QWEN_CODER_MODEL = os.getenv("QWEN_CODER_MODEL", "qwen2.5-coder:7b-instruct")

# ---- Kokoro voice rotation pool (round-robin, persisted in state.db) ----
# American + British, mixed gender. See Kokoro voice list.
VOICE_POOL = [
    "af_heart", "am_michael", "bf_emma", "bm_george",
    "af_bella", "am_adam", "bf_isabella", "bm_lewis",
]

# ---- Per-category subtitle styles (ASS). Keys must match qwen category tags. ----
# Fields map to ASS \\style: font, size, primary (&HAABBGGRR), outline color, outline px, y-position.
SUBTITLE_STYLES = {
    "history":   {"font": "Georgia",          "size": 92, "primary": "&H00FFFFFF", "outline": "&H00203A52", "outline_px": 5, "valign": 5, "highlight": "&H0000D7FF"},
    "geography": {"font": "Verdana",           "size": 90, "primary": "&H00FFFFFF", "outline": "&H00355E3B", "outline_px": 5, "valign": 5, "highlight": "&H0000E5A8"},
    "science":   {"font": "Trebuchet MS",      "size": 90, "primary": "&H00FFFFFF", "outline": "&H00802A2A", "outline_px": 5, "valign": 5, "highlight": "&H00FFC04D"},
    "default":   {"font": "Arial",             "size": 88, "primary": "&H00FFFFFF", "outline": "&H00000000", "outline_px": 5, "valign": 5, "highlight": "&H0000C8FF"},
}

def style_for(category: str) -> dict:
    return SUBTITLE_STYLES.get((category or "").lower(), SUBTITLE_STYLES["default"])

# ---- Music mood -> filename substring matcher for the local CC library ----
MOOD_KEYWORDS = {
    "epic": ["epic", "cinematic", "trailer"],
    "calm": ["calm", "ambient", "soft", "peaceful"],
    "uplifting": ["uplift", "happy", "bright", "inspire"],
    "mysterious": ["mystery", "dark", "tension", "suspense"],
    "documentary": ["doc", "neutral", "underscore", "background"],
}
