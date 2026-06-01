# Automated Reel Pipelines (Open-Source Only)

Two fully autonomous, 100% free/open-source pipelines that turn a topic into a
finished, ready-to-publish vertical reel (1080×1920, H.264/AAC) with **no manual
editing** — synchronized voiceover, category-styled subtitles, and topic-matched
music. A Discord approval loop delivers **21 drafts per pipeline every Monday
morning**; approve schedules a reel, reject generates a fresh proposition.

## Toolchain (nothing proprietary)
| Stage | Tool |
|-------|------|
| Scripting / orchestration | **qwen** (local, via Ollama/vLLM OpenAI-compatible endpoint) |
| Text-to-speech | **Kokoro TTS** (local, voice rotation) |
| Timestamps | **Whisper** (`faster-whisper`, falls back to `openai-whisper`) |
| Video/audio | **FFmpeg** |
| Glue | **Python** |
| Footage/images | **Pixabay, Pexels, optional Archive.org** (free public APIs) |
| Procedural visuals | **Pillow** key-art fallback for offline renders |
| Music | local CC/CC0 library or generated procedural bed, matched by mood |

## Pipelines
- **Pipeline A — Synthetic-Visual reel:** topic → script (qwen) → Kokoro TTS →
  locally-generated images (Stable Diffusion → Pixabay stock → procedural
  key art) → Whisper timestamps → styled subtitles → matched music → export.
- **Pipeline B — Stock-Footage documentary reel:** historical/geographic anecdote
  (qwen) → script → **rotated** Kokoro voice → footage from
  Pixabay/Pexels/optional Archive.org (license-logged) → FFmpeg edit → **category-styled**
  subtitles → matched music → export.

## Install
```powershell
# 1. Python deps
.\scripts\setup-python.ps1 -Recreate   # uses Python 3.11; required for Kokoro/SciPy wheels

# 2. FFmpeg (NOT a pip package)
winget install Gyan.FFmpeg     # then restart shell so ffmpeg is on PATH

# 3. Local qwen via Ollama
#    https://ollama.com  ->  ollama pull qwen2.5:7b-instruct  ->  ollama serve

# 4. Config
copy .env.example .env         # fill PEXELS/PIXABAY keys + Discord token/channel
# Optional: set ARCHIVE_MEDIA_ENABLED=1 if you want Archive.org lookups.

# 5. Music: drop CC0/CC tracks into music_library\  named by mood,
#    e.g. epic_cinematic_01.mp3, calm_ambient_forest.mp3, documentary_underscore.mp3

# 6. Optional Hunyuan Video backend (large: ~36GB model weights)
.\scripts\install-hunyuan.ps1 -ComfyRoot D:\ComfyUI -DownloadModels
.\scripts\start-comfy.ps1 -ComfyRoot D:\ComfyUI
```

## Usage
```powershell
.\.venv\Scripts\python.exe run.py check                              # verify environment
.\.venv\Scripts\python.exe run.py serve                              # web dashboard + API
.\.venv\Scripts\python.exe run.py a "Why the ocean is salty"         # one Pipeline A reel
.\.venv\Scripts\python.exe run.py b "The siege of Constantinople"    # one Pipeline B reel
.\.venv\Scripts\python.exe run.py batch --pipeline A --n 5           # 5 Pipeline A drafts
.\.venv\Scripts\python.exe run.py validate drafts\A_18.mp4 --workflow drafts\A_18.workflow.md
.\.venv\Scripts\python.exe run.py bot --post-now                     # Discord review now
.\scripts\verify-production.ps1                                      # full verification
```

## Approval loop
1. **Mon 08:00** (APScheduler) the bot ensures 21 `pending` drafts exist per
   pipeline, then posts each as an embed (thumbnail + title + topic + script
   preview, short MP4 attached when small) with **✅ Approve / ❌ Reject** buttons.
2. **Approve** → status `approved`, a publish slot is scheduled (spread across the
   week), and the message updates with the slot time.
3. **Reject** → status `rejected`, qwen produces a **new proposition**, a fresh
   draft is generated and re-posted for approval — repeat until the slot fills.
4. When all 21 per pipeline are approved+scheduled, the bot announces the cycle
   complete and idles until next Monday.

## Graceful degradation (so you can test before everything is installed)
- **qwen** unreachable → deterministic offline script/anecdote stubs.
- **Kokoro** missing → correctly-timed silent WAV (downstream still renders).
- **Whisper** missing → even-distribution word timing from the known script.
- **Stable Diffusion** missing → Pixabay stock → local procedural key art.
- **No media keys / Archive disabled** → local procedural key art.
- **music_library** empty → local procedural music bed.
- **FFmpeg** is the one hard requirement for an actual MP4 export.

Every downloaded asset's **source URL + license** is recorded in `state.db`
(`assets` table); only confirmable free/CC/public-domain assets are used.

## Layout
```
run.py                    entrypoint CLI
check_env.py              dependency/key checker
requirements.txt  .env.example  .gitignore
pipelines/
  pipeline_a.py           topic -> synthetic-visual reel
  pipeline_b.py           anecdote -> stock-footage reel
  batch.py                weekly 21-draft generation + reject regen
  approval_bot.py         Discord buttons + APScheduler
  common/
    config.py             paths, format, subtitle styles, voice pool, moods
    db.py                 sqlite: drafts, schedule, voice cursor, asset licenses
    qwen_client.py        topic->script / anecdote / mood / propositions
    kokoro_tts.py         local TTS + round-robin voice rotation
    whisper_timing.py     word-level timestamps
    subtitles.py          category-styled .ass (karaoke highlight)
    media_fetch.py        Archive.org / Pixabay / Pexels + license logging
    image_gen.py          SD -> stock -> placeholder image chain
    music.py              mood-matched track picker
    ffmpeg_build.py       segments, concat, burn subs, mix+duck, export
output/  drafts/  music_library/  logs/   state.db
```
