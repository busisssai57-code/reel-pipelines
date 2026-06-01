"""Hunyuan Video — text-to-video engine integration (with lip-sync for actors).

The engine is **Hunyuan Video**, driven through an open-source ComfyUI backend
over its local HTTP API (free, local, swappable). When the backend/GPU is not
available, every entry point degrades gracefully so the pipeline never blocks
(callers fall back to image_gen / footage).

Public API:
    is_available() -> bool
    render(prompt, seconds, fps, width, height, seed, steps, actor, progress_cb) -> Path|None
    lipsync(video, audio, actor) -> Path
    render_actor_shot(prompt, vo_wav, **kw) -> Path|None
"""
from __future__ import annotations
import json, os, logging, time
from pathlib import Path
import requests
from . import config, bus

log = logging.getLogger("hunyuan")

COMFY_URL = config.COMFY_URL
ENGINE_NAME = "Hunyuan Video"
LIPSYNC_MODEL = config.LIPSYNC_MODEL
_PROBE_TTL = 15.0
_probe_cache = {"t": 0.0, "ok": False}


def is_available() -> bool:
    """True only if the ComfyUI/Hunyuan Video backend is reachable. Cached briefly."""
    now = time.time()
    if now - _probe_cache["t"] < _PROBE_TTL:
        return _probe_cache["ok"]
    ok = False
    try:
        r = requests.get(f"{COMFY_URL}/system_stats", timeout=2)
        ok = r.status_code == 200
    except Exception:
        ok = False
    _probe_cache.update(t=now, ok=ok)
    return ok


def health() -> dict:
    """Machine-readable deployment status for the dashboard and checks."""
    paths = {
        "comfy_root": config.COMFY_ROOT,
        "workflow": Path(config.HUNYUAN_WORKFLOW),
        "diffusion_model": config.COMFY_ROOT / "models" / "diffusion_models" / config.HUNYUAN_MODEL,
        "vae": config.COMFY_ROOT / "models" / "vae" / config.HUNYUAN_VAE,
        "clip": config.COMFY_ROOT / "models" / "text_encoders" / config.HUNYUAN_CLIP,
        "llm": config.COMFY_ROOT / "models" / "text_encoders" / config.HUNYUAN_LLM,
    }
    return {
        "engine": ENGINE_NAME,
        "comfy_url": COMFY_URL,
        "available": is_available(),
        "lip_sync_model": LIPSYNC_MODEL,
        "paths": {k: str(v) for k, v in paths.items()},
        "installed": {k: Path(v).exists() for k, v in paths.items()},
    }


def render(prompt: str, *, seconds: float = 4.0, fps: int = config.FPS,
           width: int = 540, height: int = 960, seed: int | None = None,
           steps: int = 30, actor: str | None = None,
           progress_cb=None, job_id: str | None = None) -> Path | None:
    """Render a silent vertical clip from `prompt` via Hunyuan Video.

    Returns the mp4 path, or None if the engine is unavailable (caller falls back).
    Defaults are deliberately low-res/short so a typical PC can cope; raise for
    quality on capable GPUs.
    """
    if not is_available():
        bus.emit(job_id, "hunyuan", "degraded", f"{ENGINE_NAME} backend unavailable")
        return None
    frames = max(1, int(seconds * fps))
    bus.emit(job_id, "hunyuan", "render_start",
             f"{ENGINE_NAME} {width}x{height} {frames}f steps={steps}")
    workflow = _build_workflow(prompt, frames, fps, width, height, seed or int(time.time()), steps)
    try:
        out = _submit_and_wait(workflow, progress_cb=progress_cb, job_id=job_id)
        bus.emit(job_id, "hunyuan", "render_done", str(out))
        return out
    except Exception as e:
        bus.emit(job_id, "hunyuan", "stage_error", f"{ENGINE_NAME} render failed: {e}")
        return None


def lipsync(video: Path, audio: Path, actor: str | None = None,
            job_id: str | None = None) -> Path:
    """Drive the generated actor's mouth from `audio` using an open lip-sync model.

    If no lip-sync backend is configured/available, returns the input video
    unchanged and logs a 'degraded' event (video still ships, just not lip-synced).
    """
    video, audio = Path(video), Path(audio)
    if not LIPSYNC_MODEL or not is_available():
        bus.emit(job_id, "hunyuan", "degraded",
                 "lip-sync model not configured ([FILL: open lip-sync model])")
        return video
    bus.emit(job_id, "hunyuan", "lipsync_start", f"model={LIPSYNC_MODEL}")
    workflow = _build_lipsync_workflow(video, audio, LIPSYNC_MODEL)
    try:
        out = _submit_and_wait(workflow, job_id=job_id)
        bus.emit(job_id, "hunyuan", "lipsync_done", str(out))
        return out
    except Exception as e:
        bus.emit(job_id, "hunyuan", "stage_error", f"lip-sync failed: {e}")
        return video


def render_actor_shot(prompt: str, vo_wav: Path, *, job_id: str | None = None,
                      **kw) -> Path | None:
    """Render an actor clip and lip-sync it to the Kokoro voiceover. None if unavailable."""
    clip = render(prompt, job_id=job_id, **kw)
    if clip is None:
        return None
    return lipsync(clip, Path(vo_wav), actor=kw.get("actor"), job_id=job_id)


# --------------------------------------------------------------- ComfyUI plumbing
def _build_workflow(prompt, frames, fps, w, h, seed, steps) -> dict:
    """Return a ComfyUI API prompt for the configured Hunyuan workflow."""
    workflow_path = Path(config.HUNYUAN_WORKFLOW)
    if workflow_path.exists():
        raw = workflow_path.read_text(encoding="utf-8")
        replacements = {
            "{{PROMPT}}": prompt,
            "{{NEGATIVE_PROMPT}}": "low quality, blurry, distorted, watermark, text",
            "{{FRAMES}}": str(frames),
            "{{FPS}}": str(fps),
            "{{WIDTH}}": str(w),
            "{{HEIGHT}}": str(h),
            "{{SEED}}": str(seed),
            "{{STEPS}}": str(steps),
            "{{HUNYUAN_MODEL}}": config.HUNYUAN_MODEL,
            "{{HUNYUAN_VAE}}": config.HUNYUAN_VAE,
            "{{HUNYUAN_CLIP}}": config.HUNYUAN_CLIP,
            "{{HUNYUAN_LLM}}": config.HUNYUAN_LLM,
        }
        for key, value in replacements.items():
            raw = raw.replace(key, value.replace("\\", "\\\\").replace('"', '\\"'))
        return json.loads(raw)
    # Explicitly fail rather than sending a fake graph to ComfyUI.
    raise FileNotFoundError(f"Hunyuan workflow file not found: {workflow_path}")


def _build_lipsync_workflow(video: Path, audio: Path, model: str) -> dict:
    return {"_lipsync": model, "video": str(video), "audio": str(audio)}


def _submit_and_wait(workflow: dict, *, progress_cb=None, job_id=None,
                     timeout: float = 1800) -> Path:
    """POST the workflow to ComfyUI, poll history, return the produced mp4.

    Implemented against ComfyUI's /prompt + /history endpoints. The exact output
    file plumbing depends on the installed Save nodes; adapt _extract_output().
    """
    r = requests.post(f"{COMFY_URL}/prompt", json={"prompt": workflow}, timeout=10)
    r.raise_for_status()
    pid = r.json().get("prompt_id")
    start = time.time()
    while time.time() - start < timeout:
        if job_id and bus.is_canceled(job_id):
            raise RuntimeError("canceled")
        h = requests.get(f"{COMFY_URL}/history/{pid}", timeout=10)
        data = h.json() if h.ok else {}
        if pid in data:
            return _extract_output(data[pid])
        if progress_cb:
            progress_cb(min(0.95, (time.time() - start) / timeout))
        time.sleep(1.0)
    raise TimeoutError(f"{ENGINE_NAME} render timed out")


def _extract_output(history_entry: dict) -> Path:
    for node in history_entry.get("outputs", {}).values():
        for key in ("gifs", "videos", "images"):
            for item in node.get(key, []):
                fn = item.get("filename")
                sub = item.get("subfolder", "")
                if fn:
                    return Path(os.getenv("COMFY_OUTPUT", "."), sub, fn)
    raise RuntimeError("no output produced by Hunyuan Video workflow")
