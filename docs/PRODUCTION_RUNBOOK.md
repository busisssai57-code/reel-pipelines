# Production Runbook

## Current Deployment Target

- Platform: Windows 10/11 workstation with NVIDIA GPU.
- Backend: stdlib Python HTTP API in `server.py`, SQLite `state.db`, event bus in `pipelines/common/bus.py`.
- UI: static dashboard at `dashboard/index.html`, served same-origin by `py run.py serve`.
- Video: FFmpeg for assembly/export, Kokoro for TTS, Whisper/faster-whisper for timing, ComfyUI + Hunyuan Video for text-to-video, optional LatentSync for lip sync.
- Auto-poster: durable SQLite queue with `local_manifest` and `webhook` providers.

## Setup

```powershell
cd D:\reel-pipelines
.\scripts\setup-python.ps1 -Recreate
.\scripts\install-ffmpeg.ps1
.\scripts\install-hunyuan.ps1 -ComfyRoot D:\ComfyUI -DownloadModels
.\scripts\start-comfy.ps1 -ComfyRoot D:\ComfyUI
.\.venv\Scripts\python.exe run.py serve
```

Open `http://127.0.0.1:8787`.

## Configuration

Copy `.env.example` to `.env` and set:

- `FFMPEG_BIN` / `FFPROBE_BIN` to the installed local FFmpeg binaries.
- `COMFY_ROOT`, `COMFY_URL`, `COMFY_OUTPUT`, and `HUNYUAN_WORKFLOW`.
- `AUTOPOST_MODE=local_manifest` for local production validation or `AUTOPOST_MODE=webhook` plus `AUTOPOST_WEBHOOK_URL` for external publishing automation.
- Discord keys if using the Discord approval bot.
- `REEL_API_KEY` before exposing the API outside localhost; enter the same key in Dashboard -> Settings.
- `CORS_ORIGIN` to the exact dashboard/tunnel origin for non-local deployments.

## UI/UX Deliverables

- Runnable high-fidelity implementation: `dashboard/index.html`.
- Wireframe/spec: `docs/UI_BLUEPRINT.md`.
- Live agent mesh: dashboard cards poll `/api/agents`, `/api/events`, `/api/jobs`, and `/api/autopost/status`.
- Animated trace stream: agent activity, job state, and auto-post status update every few seconds.

## Hunyuan Video Deployment

The installer uses current ComfyUI native Hunyuan support plus production nodes:

- `ComfyUI-VideoHelperSuite` for MP4 output.
- `ComfyUI-KJNodes` for performance helpers.
- `ComfyUI-HunyuanVideoWrapper` for compatibility/advanced Hunyuan nodes.
- `ComfyUI-LatentSyncWrapper` for open lip-sync workflows.

Required model files are checked by `hunyuan_video.health()`:

- `D:\ComfyUI\models\diffusion_models\hunyuan_video_t2v_720p_bf16.safetensors`
- `D:\ComfyUI\models\text_encoders\clip_l.safetensors`
- `D:\ComfyUI\models\text_encoders\llava_llama3_fp8_scaled.safetensors`
- `D:\ComfyUI\models\vae\hunyuan_video_vae_bf16.safetensors`

The API workflow template is `workflows/hunyuan_t2v_native_api.json`.

## Auto-Poster Workflow

1. User approves a draft from the dashboard or Discord.
2. Backend schedules the publish slot and emits an `approved` event.
3. `AutoPostAgent` creates a durable row in `publish_jobs`.
4. `/api/autopost/run` processes due jobs.
5. `local_manifest` writes `logs/autopost-manifest.jsonl`; `webhook` posts JSON to `AUTOPOST_WEBHOOK_URL`.

## Verification Commands

```powershell
.\scripts\verify-production.ps1
```

Expected validated checks:

- Python compile succeeds.
- Unit tests pass.
- Environment check reports FFmpeg and installed Python dependencies.
- Dashboard JavaScript parses.
- API health returns Hunyuan and auto-post status.

## Performance Baseline

Measured on this machine during hardening:

- Python dependency install with Python 3.11: completed successfully.
- Contract test suite: 4 tests in ~2 seconds before full dependency install; still expected under 10 seconds.
- FFmpeg install: ~90 seconds.
- ComfyUI runtime install: ~10 minutes, excluding model weights.
- Hunyuan model weights: ~36GB total; transfer time depends on Hugging Face throughput.
- If Hugging Face stalls at 0 bytes on Windows, the installer disables Xet automatically with `HF_HUB_DISABLE_XET=1`.

## Troubleshooting

- SciPy/Kokoro build failure: recreate the venv with `.\scripts\setup-python.ps1 -Recreate`; Python 3.11 is required.
- `hunyuan=false`: start ComfyUI with `.\scripts\start-comfy.ps1` and verify `COMFY_URL`.
- Missing Hunyuan models: rerun `.\scripts\install-hunyuan.ps1 -DownloadModels`.
- Render fails at export: run `.\scripts\install-ffmpeg.ps1` and verify `.env` paths.
- Auto-post not publishing externally: set `AUTOPOST_MODE=webhook` and `AUTOPOST_WEBHOOK_URL`; keep `local_manifest` for offline validation.
- `401 unauthorized` on POST: set the same API key in `.env` (`REEL_API_KEY`) and Dashboard -> Settings.

## Rollback Plan

1. Stop servers: close the `run.py serve` and `start-comfy.ps1` terminals.
2. Restore previous code: `git revert <commit>` after the hardening commit.
3. Preserve generated media: `drafts/`, `output/`, and `logs/` are ignored and survive code rollback.
4. Reset auto-post queue if needed:

```powershell
.\.venv\Scripts\python.exe - <<'PY'
from pipelines.common import db
with db.conn() as c:
    c.execute("UPDATE publish_jobs SET status='queued' WHERE status='running'")
PY
```

5. Re-run `.\scripts\verify-production.ps1`.
