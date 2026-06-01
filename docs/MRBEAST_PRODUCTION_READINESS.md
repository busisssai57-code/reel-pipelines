# MrBeast-Style Production Readiness Report

This project cannot honestly claim final Hunyuan/lip-sync readiness until the full
Hunyuan model set finishes downloading and ComfyUI is running. The rest of the
local reel pipeline is now measurable: scripts are scored, exports are probed,
music and visuals have offline fallbacks, and a rendered artifact exists.

## Current Validation Artifact

- Video: `drafts/A_18.mp4`
- Thumbnail: `drafts/A_18.jpg`
- Workflow card: `drafts/A_18.workflow.md`
- Machine quality report: `drafts/A_18.quality.json`
- Auto-post manifest: `logs/autopost-manifest.jsonl`
- Topic: `Building a zero-budget backyard obstacle course challenge`
- Voice: Kokoro `af_heart`
- Runtime: 28.5 seconds
- Format: 1080x1920, 30fps, H.264/AAC

Second validation artifact:

- Video: `drafts/B_32.mp4`
- Workflow card: `drafts/B_32.workflow.md`
- Machine quality report: `drafts/B_32.quality.json`
- Runtime: 30.83 seconds
- Format: 1080x1920, 30fps, H.264/AAC
- Script score: 1.0
- Export score: 1.0

## Production Gates

Script gates in `pipelines/common/quality.py`:

- Hook appears in the opening words.
- Title includes a strong retention/stakes signal.
- Beat count stays between 5 and 8.
- Word count stays in a short-form production range.
- Every beat has a visual prompt.
- Unverified superlatives such as `world's`, `guaranteed`, and `#1` are blocked.

Export gates:

- MP4 exists.
- Duration is valid for short-form publishing.
- Resolution is exactly 1080x1920.
- Audio stream is present.
- Workflow card exists next to the video.

## Autofixes Applied

- Weak script specs are expanded with enough beats, prompts, and pacing to render.
- Empty music libraries now generate a local procedural music bed.
- Missing external imagery now generates offline procedural key art instead of a plain gradient when Pillow is installed.
- FFmpeg music ducking now splits the voice stream before sidechain compression, fixing the generated-music export failure.
- Still-image rendering uses a fast 1080x1920 path so validation runs complete on local CPU.
- Hunyuan health now checks minimum model byte sizes instead of accepting partial files as installed.

## Hunyuan Status

The Hunyuan installer is still downloading large model weights. `run.py check`
currently reports partial model files, so Hunyuan and lip-sync rendering are not
marked passed. Once downloads finish:

```powershell
.\scripts\start-comfy.ps1 -ComfyRoot D:\ComfyUI
.\.venv\Scripts\python.exe run.py check
.\.venv\Scripts\python.exe run.py a "high stakes creator challenge" 
```

The Hunyuan backend must report available before a lip-synced Hunyuan render can
be validated.

## Live Demonstration Plan

1. Start the studio:

```powershell
cd D:\reel-pipelines
.\.venv\Scripts\python.exe run.py serve
```

2. Open `http://127.0.0.1:8787`.
3. Render a new Pipeline A draft from the dashboard or CLI.
4. Confirm live telemetry updates in the agent mesh and trace stream.
5. Open the produced MP4, workflow card, and `.quality.json`.
6. Approve the draft in the dashboard.
7. Run auto-post locally:

```powershell
.\.venv\Scripts\python.exe -c "from pipelines.common import autopost; print(autopost.queue_due_approved()); print(autopost.run_once())"
```

8. Verify `logs/autopost-manifest.jsonl` contains the publish payload.

## Acceptance Criteria

The non-Hunyuan path is accepted when:

- `.\.venv\Scripts\python.exe -m unittest discover -s tests -v` passes.
- `.\.venv\Scripts\python.exe run.py check` reports FFmpeg and Python deps OK.
- A rendered artifact passes `run.py validate`.
- The artifact has MP4, JPG thumbnail, workflow JSON/MD, and quality JSON.
- Auto-post can queue the rendered draft and write a local manifest. Validated with draft `18`.
- Scheduled auto-post jobs do not publish early. Validated by approving draft `32`, queueing publish job `20`, and running due jobs with `processed=0`.

The Hunyuan path is accepted only after all model files meet minimum sizes,
ComfyUI responds at `COMFY_URL`, and a Hunyuan-generated MP4 passes the same
export gates.
