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

## Verification Evidence

- `py -m unittest discover -s tests -v`: 4 tests passed before dependency install.
- `.\scripts\setup-python.ps1 -Recreate`: Python 3.11 venv created, project dependencies installed, tests passed.
- `.\scripts\install-ffmpeg.ps1`: installed FFmpeg 8.1.1 essentials locally.
- `.\scripts\install-hunyuan.ps1 -ComfyRoot D:\ComfyUI`: installed ComfyUI runtime and custom nodes.
- `.\scripts\install-hunyuan.ps1 -ComfyRoot D:\ComfyUI -DownloadModels`: initial Hugging Face transfer stalled with Xet; retry with Xet disabled began downloading.

## Remaining External Dependencies

- Hunyuan model weight download requires Hugging Face network access and ~36GB disk.
- External platform publishing requires platform credentials or a webhook automation endpoint.
