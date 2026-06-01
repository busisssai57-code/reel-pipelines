# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**reel-pipelines** is an open-source, fully autonomous system that turns topics into finished vertical video reels (1080×1920, H.264/AAC) with no manual editing. It generates synchronized voiceover, category-styled subtitles, and topic-matched music.

Two independent pipelines:
- **Pipeline A**: Topic → Script (Qwen LLM) → TTS → Synthetic visuals (Hunyuan Video or Stable Diffusion) → Subtitles → Music → Export
- **Pipeline B**: Topic → Anecdote → TTS (with voice rotation) → Stock footage (Pixabay/Pexels) → Subtitles → Music → Export

Key feature: A Discord approval bot runs weekly, delivering 21 draft reels per pipeline for user approval. Approved reels are auto-published; rejected ones trigger a new proposition and fresh render.

## Core Architecture Patterns

### Event Bus + Supervisor
All render pipelines use an **event bus** (`pipelines/common/bus.py`) for async event emission and a **Supervisor** (`pipelines/common/supervisor.py`) framework that provides:

- **Self-correction**: Validated retries with exponential backoff via `run_stage()`
- **Self-healing**: Documented fallbacks (e.g., Pipeline A falls back to stock images if Hunyuan Video fails)
- **Self-improvement**: Circuit breakers trip agents after repeated failures; outcome scores update persisted priors that bias future choices
- **Graceful degradation**: Missing dependencies (Qwen, Kokoro, Whisper, Hunyuan) fail over to deterministic stubs or generated fallbacks

### Agent System
Agents (`pipelines/agents.py`) subscribe to event types and react:
- `TriggerAgent`: Creates render jobs (UI button, cron, reject loop)
- `VisualQAAgent`: Validates finished reel duration vs. voiceover
- `AutoPostAgent`: Publishes/schedules a draft after approval
- `AudienceFeedbackAgent`: Turns engagement signals into scores
- `VariantGenAgent`: Makes viral variants of approved drafts
- `EpisodesAgent`: Series reproduction ("episodes mode")

Each agent has a circuit breaker guard that prevents cascading failures.

## Common Development Commands

All commands use `run.py` from the `.venv` interpreter:

```powershell
# Environment & Setup
.\scripts\setup-python.ps1 -Recreate              # Rebuild venv (Python 3.11 required for Kokoro/SciPy wheels)
.\scripts\install-ffmpeg.ps1                       # Install FFmpeg (non-pip dependency)
.\scripts\install-hunyuan.ps1 -ComfyRoot D:\ComfyUI -DownloadModels  # Hunyuan Video backend (~36GB)
.\scripts\start-comfy.ps1 -ComfyRoot D:\ComfyUI   # Launch ComfyUI server (required for Hunyuan)

# Single Reel Generation
.\.venv\Scripts\python.exe run.py a "Why the ocean is salty"          # Pipeline A
.\.venv\Scripts\python.exe run.py b "The siege of Constantinople"     # Pipeline B
.\.venv\Scripts\python.exe run.py b ""                                # Pipeline B: auto-pick topic

# Batch & Weekly Generation
.\.venv\Scripts\python.exe run.py batch                               # Generate 21 drafts each pipeline
.\.venv\Scripts\python.exe run.py batch --pipeline A --n 5            # 5 Pipeline A drafts
.\.venv\Scripts\python.exe run.py batch --pipeline B --n 3            # 3 Pipeline B drafts

# Discord Bot & Approval Loop
.\.venv\Scripts\python.exe run.py bot                                 # Run approval bot + weekly scheduler
.\.venv\Scripts\python.exe run.py bot --post-now                      # Post weekly review immediately

# Web Dashboard & API
.\.venv\Scripts\python.exe run.py serve [--port 8787] [--no-open]     # Start dashboard at http://127.0.0.1:8787

# Validation & Diagnostics
.\.venv\Scripts\python.exe run.py check                               # Environment & dependency verification
.\.venv\Scripts\python.exe run.py validate drafts\A_18.mp4 [--workflow drafts\A_18.workflow.md]
.\scripts\verify-production.ps1                                       # Full production validation suite
```

## Key Modules

### Pipeline Modules
- `pipeline_a.py`: Synthetic-visual reel orchestration; coordinates Qwen → TTS → Hunyuan/Stable Diffusion → subtitles → music → export
- `pipeline_b.py`: Stock-footage documentary reel; handles archive/Pixabay/Pexels lookups, voice rotation, and footage Ken-Burns
- `batch.py`: Weekly 21-draft generation and rejection regeneration
- `approval_bot.py`: Discord bot with approve/reject buttons and APScheduler integration
- `agents.py`: Agent definitions for render triggers, QA, auto-post, feedback loop, variants, episodes

### Common Utilities (in `pipelines/common/`)
- `config.py`: Paths, render formats, subtitle styles, voice pool, mood mappings
- `db.py`: SQLite schema (drafts, schedules, voice cursor, asset licenses, publish jobs)
- `bus.py`: Event emission and job cancellation; used for real-time dashboard updates
- `supervisor.py`: `run_stage()`, `CircuitBreaker`, and outcome-score persistence
- `qwen_client.py`: Topic→script, anecdote generation, mood classification, proposition regeneration (uses local Qwen via OpenAI-compatible endpoint)
- `kokoro_tts.py`: Local TTS with voice rotation (round-robin)
- `whisper_timing.py`: Word-level timestamps; falls back to even distribution if Whisper unavailable
- `subtitles.py`: Category-styled .ass subtitles with karaoke highlight
- `media_fetch.py`: Archive.org, Pixabay, Pexels API calls with license logging to `state.db`
- `image_gen.py`: Stable Diffusion → stock → procedural placeholder chain
- `music.py`: Mood-matched track picker (library in `music_library/` or local procedural bed)
- `ffmpeg_build.py`: Segments, concat, burn subs, mix+duck audio, export to 1080×1920 H.264/AAC
- `hunyuan_video.py`: ComfyUI + Hunyuan Video orchestration for text-to-video + lip-sync
- `quality.py`: Validation checks (duration, resolution, audio, workflow card)
- `workflow_card.py`: Render metadata card (script, settings, outcome scores) burned into export
- `thumbnails.py`: Auto-generate preview images for dashboard/Discord
- `autopost.py`: Durable queue-based publishing (local manifest or webhook)
- `topic_engine.py`: Topic/anecdote proposition and caching

## Configuration

### `.env` Required Keys
```
# LLM orchestration (local Qwen endpoint)
OPENAI_API_KEY=not-used-for-local
OPENAI_API_BASE=http://localhost:11434/v1  # Ollama default; set for vLLM

# API credentials (free public APIs)
PIXABAY_KEY=<your-key>
PEXELS_KEY=<your-key>

# Discord approval bot
DISCORD_TOKEN=<bot-token>
DISCORD_CHANNEL_ID=<channel-id>

# ComfyUI + Hunyuan Video
COMFY_URL=http://127.0.0.1:8188
COMFY_OUTPUT=D:\ComfyUI\output
HUNYUAN_WORKFLOW=workflows/hunyuan_t2v_native_api.json

# FFmpeg (if not on PATH)
FFMPEG_BIN=C:\path\to\ffmpeg.exe
FFPROBE_BIN=C:\path\to\ffprobe.exe

# Publishing
AUTOPOST_MODE=local_manifest    # or webhook
AUTOPOST_WEBHOOK_URL=<optional>

# Security
REEL_API_KEY=<set-before-exposing-api>
CORS_ORIGIN=http://127.0.0.1:8787

# Optional features
ARCHIVE_MEDIA_ENABLED=0         # Archive.org lookups (disabled by default for offline operation)
```

## Database Schema

**state.db** (SQLite):
- `drafts`: id, topic, script, pipeline, status (pending/approved/rejected/published), created, rendered_path, duration, quality_json
- `publish_jobs`: id, draft_id, status (queued/running/done), publish_slot, created
- `voice_cursor`: last_voice_index (round-robin state)
- `assets`: url, license_type, used_in_draft (license audit trail)
- `priors`: key (circuit breaker state, outcome scores, topic cache)

## Development Notes

### Adding a New Stage to a Pipeline
Use `supervisor.run_stage()` with validation:
```python
from .common import supervisor

output = supervisor.run_stage(
    supervisor.Stage(
        name="my_stage",
        execute=lambda job, attempt, **kw: my_function(**kw),
        validate=lambda o: (isinstance(o, str), "expected string"),
        fallback=lambda job: "fallback_value",
        max_retries=3
    ),
    job
)
```

### Adding a New Agent
Subclass or create a dataclass following `pipelines/agents.py` pattern:
```python
@dataclass
class MyAgent(Agent):
    def __init__(self):
        super().__init__(name="my_agent", subscribes=("event_type",))
    
    def handle(self, event: dict) -> list[dict]:
        # Return list of new events to emit
        return []
```

### Testing Locally Without All Dependencies
- Qwen unreachable → deterministic offline stubs
- Kokoro missing → silent WAV
- Whisper missing → even word distribution
- Stable Diffusion missing → Pixabay stock → procedural art
- Music library empty → procedural bed
- FFmpeg required (hard requirement for MP4 export)

### Performance Baselines
- Python 3.11 venv setup: ~1–2 min
- Contract test suite: ~2 sec (6 tests)
- Single Pipeline A render: ~28–30 sec (Kokoro + subtitles + music + export)
- Single Pipeline B render: ~30–33 sec (stock footage + subtitles + music + export)
- FFmpeg install: ~90 sec
- ComfyUI + Hunyuan: ~10 min runtime, ~36GB model weights

## Troubleshooting

| Issue | Solution |
|-------|----------|
| SciPy/Kokoro build fails | `.\scripts\setup-python.ps1 -Recreate` (Python 3.11 required) |
| `hunyuan=false` in health check | Start ComfyUI: `.\scripts\start-comfy.ps1` and verify `COMFY_URL` |
| Missing Hunyuan models | `.\scripts\install-hunyuan.ps1 -DownloadModels` |
| Render fails at export | `.\scripts\install-ffmpeg.ps1` and verify `.env` paths |
| Empty music library | Procedural bed is generated; add CC0 tracks to `music_library/` for custom branding |
| No stock/image API keys | Procedural key art is generated via Pillow |
| Slow Archive.org | Keep `ARCHIVE_MEDIA_ENABLED=0` for offline; enable only when network media is desired |
| Auto-post not publishing | Set `AUTOPOST_MODE=webhook` + `AUTOPOST_WEBHOOK_URL` |
| `401 unauthorized` on API POST | Set same key in `.env` (`REEL_API_KEY`) and Dashboard → Settings |

## Production Deployment Notes

- **Platform**: Windows 10/11 workstation with NVIDIA GPU (optional for faster Hunyuan renders)
- **Backend**: stdlib Python HTTP API (`server.py`), SQLite `state.db`, event bus
- **UI**: Static dashboard (`dashboard/index.html`), served same-origin; polls `/api/agents`, `/api/events`, `/api/jobs`, `/api/autopost/status` every few seconds
- **Durable publishing queue**: SQLite-backed with `local_manifest` (for validation) or `webhook` (for external publishing)
- **Rollback**: `git revert <commit>`; `drafts/`, `output/`, `logs/` survive and are not rolled back

## Code Style & Testing

- Single-source-of-truth for configuration: `pipelines/common/config.py`
- All long-running operations use the `supervisor.run_stage()` pattern for self-correction + fallback
- Event bus for all inter-agent communication; agents are intentionally stateless
- No external ML services; all AI/ML is local (Qwen, Kokoro, Whisper, Stable Diffusion, Hunyuan)
- Graceful degradation over hard failures: missing components emit warnings and fall back to deterministic stubs or lower-quality outputs
