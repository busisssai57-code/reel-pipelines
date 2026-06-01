# Autonomic Fix Log

## Issues Detected And Fixed

- **Dashboard was mock-first.** It now loads real drafts, jobs, events, agents, and auto-post state from the backend when connected.
- **No durable auto-poster.** Added `publish_jobs`, queueing, local manifest publishing, webhook publishing, and dashboard/API controls.
- **Hunyuan workflow was a placeholder.** Added a ComfyUI API workflow template and made `hunyuan_video.py` fail explicitly if the workflow is missing instead of sending fake prompts.
- **Hunyuan install was undocumented/manual.** Added installer/start scripts for ComfyUI, Hunyuan custom nodes, VideoHelperSuite, LatentSync, and model downloads.
- **FFmpeg was missing.** Added local FFmpeg installer and wired `.env` paths.
- **Python 3.15 venv broke Kokoro/SciPy.** Added `scripts/setup-python.ps1` and updated docs to force Python 3.11.
- **Hugging Face large-file transfer stalled at 0 bytes.** Updated Hunyuan installer to disable Xet (`HF_HUB_DISABLE_XET=1`) and use `hf_hub_download()` directly.
- **API had no optional auth gate.** Added `REEL_API_KEY` / `X-API-Key` support plus configurable CORS origin for network/tunnel exposure.
- **No production tests.** Added unit tests for Hunyuan health, workflow rendering contract, auto-post queue, and dashboard operability markers.
- **Static dashboard copy drift.** The served dashboard and `dashboard/bta-site/index.html` are synced after UI changes.
- **Partial Hunyuan files were reported as installed.** Hunyuan health now checks minimum byte sizes for the diffusion model, text encoders, and VAE.
- **Fallback visuals were too basic.** Added Pillow-backed procedural key art for fully local renders when Stable Diffusion and stock APIs are unavailable.
- **Empty music library produced silent exports.** Added a local procedural music-bed generator by mood.
- **Generated-music export failed.** FFmpeg now splits the normalized voice stream before sidechain ducking and mixing.
- **Full-resolution Ken Burns validation was too slow.** The still-image render path now uses a fast 1080x1920 segment export suitable for repeatable local validation.
- **No formal production gate existed.** Added script and export scoring plus `.quality.json` sidecars.
- **Pipeline B could hang on Archive.org media lookup.** Archive.org is now opt-in (`ARCHIVE_MEDIA_ENABLED=1`); local/offline default falls back quickly to generated visuals.
- **Dashboard/health checks failed on HTTP HEAD.** Added `do_HEAD` support for dashboard, media, and API paths; covered by regression test.
- **Review queue showed already-published/failed drafts.** Queue view now filters to pending drafts and shows an empty state when no reviewable drafts remain.
- **Auto-post button implied forced publishing.** Renamed dashboard action to `Run due now` to match scheduler-safe behavior.
- **Pipeline B hook autofix accepted late hooks.** Autofix now evaluates the opening words with the same rule used by the quality scorer.
- **Auto-post test polluted the real manifest.** Unit test now writes manifests into a temporary log directory.

## Verification Evidence

- `py -m unittest discover -s tests -v`: 4 tests passed before dependency install.
- `.\scripts\setup-python.ps1 -Recreate`: Python 3.11 venv created, project dependencies installed, tests passed.
- `.\scripts\install-ffmpeg.ps1`: installed FFmpeg 8.1.1 essentials locally.
- `.\scripts\install-hunyuan.ps1 -ComfyRoot D:\ComfyUI`: installed ComfyUI runtime and custom nodes.
- `.\scripts\install-hunyuan.ps1 -ComfyRoot D:\ComfyUI -DownloadModels`: initial Hugging Face transfer stalled with Xet; retry with Xet disabled began downloading.
- `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`: 6 tests passed after quality, music, Hunyuan-size, and FFmpeg mix fixes.
- `.\.venv\Scripts\python.exe run.py a "Building a zero-budget backyard obstacle course challenge"`: rendered `drafts/A_18.mp4`.
- `.\.venv\Scripts\python.exe run.py validate drafts\A_18.mp4 --workflow drafts\A_18.workflow.md`: export score `1.0`, 1080x1920, 30fps, audio present.
- Auto-post validation on rendered draft `18`: queued `local_manifest` job and wrote `logs/autopost-manifest.jsonl`.
- Browser UI verification: dashboard loaded at `http://127.0.0.1:8787`, XHR endpoints returned 200, no application console errors observed.
- Pipeline B validation: rendered `drafts/B_32.mp4`; script score `1.0`, export score `1.0`, 1080x1920, 30fps, audio present.
- API approval/autopost validation: approved draft `32`, queued publish job `20`, and confirmed future scheduled job did not publish early.

## Remaining External Dependencies

- Hunyuan model weight download requires Hugging Face network access and ~36GB disk.
- External platform publishing requires platform credentials or a webhook automation endpoint.
