# Paste-Ready Implementation Prompt
## Modern UI + Self-Improving Multi-Agent Reel Pipeline with Hunyuan Video (lip-synced text-to-video)

> Feed this whole document to your build agent. It targets the existing
> **Reel Pipeline** repo (Pipelines A & B: qwen scripting, Kokoro TTS, Whisper
> timing, FFmpeg, Archive.org/Pixabay/Pexels, Discord approval loop, and the
> `dashboard/` web UI). Everything specified must be **free and open-source**.

---

### Role & objective
You are an expert UI/UX designer + full-stack engineer. Extend the current
open-source pipeline with: (1) a modern, animated UI; (2) self-correction,
self-healing, and self-improvement loops; (3) a set of cooperating agents
(trigger, visual QA, audience feedback, auto-post-after-approval, viral-variant
generation, **episodes mode** [a.k.a. "epsideos mode"]); (4) an integrated
text-to-video rendering engine that **must be named "Hunyuan Video"** and
**must include lip-sync for generated actors**; and (5) a **trigger button** in
the UI that controls Hunyuan Video rendering. All must run acceptably on a
typical user PC (see Performance), with graceful degradation when it can't.

**Hard do-nots:** do not introduce proprietary components; do not drop the
lip-sync requirement; do not rename or omit the **Hunyuan Video** engine; do not
remove any agent or feature listed here. Where a fact is unknown, leave an
explicit `[FILL: …]` placeholder rather than inventing it.

---

### 1. Context — current pipeline (the thing being upgraded)
- `pipelines/pipeline_a.py` — topic → qwen script → Kokoro TTS → local images → Whisper timestamps → styled `.ass` subtitles → mood-matched music → FFmpeg export (1080×1920 H.264/AAC).
- `pipelines/pipeline_b.py` — anecdote → script → **rotated** Kokoro voice → Archive.org/Pixabay/Pexels footage → FFmpeg edit → category-styled subtitles → music → export.
- `pipelines/batch.py` — generates 21 drafts/pipeline/week; reject → new qwen proposition → regen.
- `pipelines/approval_bot.py` — Discord Approve/Reject + APScheduler (Mon 08:00).
- `pipelines/common/` — `config, db (sqlite), qwen_client, kokoro_tts, whisper_timing, subtitles, media_fetch, image_gen, music, ffmpeg_build`.
- `dashboard/index.html` — existing static review UI (week meter, queue, schedule).
- New engine slots in as a visual source alongside `image_gen` / `media_fetch`.

---

### 2. UI — component specs & wireframes
Build on the existing `dashboard/` (same design tokens: 8px scale, system font,
auto dark/light, 44px targets, WCAG 2.2 AA). Add these views/components:

**New nav items:** `Render Studio`, `Agents`, `Variant Lab`, `Episodes`.

**2.1 Render Studio (Hunyuan Video control)**
```
┌───────────────────────────────────────────────┐
│ Render Studio                      GPU ● 9.1GB │
│ ┌───────────────┐  Prompt / shot list ▾        │
│ │ 9:16 preview  │  Actor: [select ▾]  lip-sync✔ │
│ │  (live frames │  Voice track: vo.wav (Kokoro) │
│ │   stream in)  │  Res: [540p▾] Frames:[129]   │
│ └───────────────┘  Steps:[30] Seed:[rand]      │
│  ◖ render 42% ◗ ETA 3m12s   [■ Cancel]         │
│        ┌──────────────────────────────────┐    │
│        │   ▶  TRIGGER  RENDER  (Hunyuan)   │    │  ← primary trigger button
│        └──────────────────────────────────┘    │
│  Queue: 3 jobs · last error: none · [Retry]    │
└───────────────────────────────────────────────┘
```
**2.2 Agents** — live board: one card per agent (name, status pill
idle/running/healing/failed, last run, throughput, mini log, pause/resume).
Edges animate when a message passes between agents.

**2.3 Variant Lab** — grid of generated viral variants of one draft
(different hook/caption/pacing/thumbnail), each with predicted-score chip and
"promote to queue".

**2.4 Episodes ("epsideos mode")** — series manager: define a recurring
format/character, auto-generate sequential episodes (E01, E02…), shared
actor/voice/style, "reproduce episode" to re-render with tweaks.

**Component inventory (additions):** Trigger Render button (state machine
below), GPU/VRAM gauge, job-queue list, agent status card, animated pipeline
graph (nodes + flowing edges), variant card w/ score, episode timeline,
toast/undo, render-preview player (poster→frames→final).

---

### 3. Multi-agent data flow
```
                 ┌───────────────┐
   topic/seed →  │  Trigger Agent │ ── enqueues job ──┐
                 └───────────────┘                    ▼
  qwen script ─► Kokoro TTS ─► Whisper ─► [VISUAL SOURCE]
                                            ├─ image_gen / media_fetch
                                            └─ Hunyuan Video (+lip-sync) ◄── actor + vo.wav
                                                     │
                                            FFmpeg assemble + subs + music
                                                     │
                 ┌───────────────┐   pass/fail + notes
                 │ Visual QA Agent│ ◄────────────────┘
                 └──────┬─────────┘
                  fail → Self-Heal (retry/repair) ── re-enqueue
                  pass ▼
                 ┌────────────────────┐
                 │ Variant Gen Agent  │ → N viral variants → Variant Lab
                 └─────────┬──────────┘
                           ▼
                 ┌────────────────────┐   Discord / dashboard
                 │ Audience Feedback  │ ◄── reactions, watch-time, A/B
                 │ Agent (scores)     │ ──► Self-Improvement store
                 └─────────┬──────────┘
                           ▼  (on user Approve)
                 ┌────────────────────┐
                 │ Auto-Post Agent    │ → schedules/publishes after approval
                 └────────────────────┘
```
All agents communicate through a simple message bus (sqlite-backed job/event
table + in-proc async queue; pluggable to Redis later). Every event is logged.

---

### 4. Self-correction / self-healing / self-improvement
**Self-correction (per job):** each stage validates its output
(e.g., Whisper word count ≈ script tokens; FFmpeg exit 0; video duration ≈ VO
duration ±5%; Hunyuan frame count == requested). On mismatch, the stage retries
with adjusted params before failing.

**Self-healing (system):** a Supervisor wraps every agent:
- exponential-backoff retries with jitter; circuit-breaker after N fails;
- dependency probes (FFmpeg on PATH, qwen endpoint up, GPU/VRAM free); if a
  dependency is down, the agent degrades to a documented fallback (e.g., Hunyuan
  → stock footage / images) and emits a `degraded` event instead of crashing;
- crash → quarantine the job, alert in UI/Discord, auto-resume on recovery;
- idempotent job IDs so retries never double-post or double-schedule.

**Self-improvement (across runs):** store outcome signals (Visual-QA scores,
audience watch-time/reactions, approve/reject) keyed by features
(hook style, pacing, voice, category, music mood, render params). A lightweight
optimizer (bandit / weighted sampling — no proprietary ML services) updates the
generation priors so future drafts favor higher-scoring choices. All weights
live in `state.db` and are inspectable in the Agents view.

**Example routine (pseudocode):**
```python
def run_stage(stage, job):
    for attempt in range(stage.max_retries):
        out = stage.execute(job, params=stage.params_for(job, attempt))
        ok, notes = stage.validate(out)
        if ok: return out
        log_event(job.id, stage.name, "self_correct", notes, attempt)
    if stage.fallback:                       # self-heal
        log_event(job.id, stage.name, "degraded", "using fallback")
        return stage.fallback(job)
    raise StageFailed(stage.name, notes)

def learn(outcome):                          # self-improve
    feats = extract_features(outcome.draft)
    priors.update(feats, reward=outcome.score)   # bandit update, persisted
```

---

### 5. Agent interfaces (roles · inputs · outputs · triggers)
| Agent | Role | Inputs | Outputs | Trigger |
|---|---|---|---|---|
| **Trigger Agent** | entrypoint; creates jobs | topic/seed, schedule, UI button | job records on bus | UI **Trigger Render** button, cron, or reject-loop |
| **Visual QA Agent** | pass/fail rendered reel | final mp4, script, timings | score + notes; pass/fail | on render complete |
| **Audience Feedback Agent** | collect engagement | Discord reactions, watch-time, A/B results `[FILL: analytics source]` | per-variant scores | on publish + polling |
| **Auto-Post Agent** | publish after approval | approved draft, schedule slot | posted/scheduled status | on user Approve |
| **Variant Gen Agent** | make viral variants | approved draft, priors | N variants (hook/caption/pacing/thumb) | on QA pass |
| **Episodes Agent** ("epsideos mode") | series + reproduce episodes | series spec (actor/voice/style), prev episodes | E0n drafts, re-renders | series schedule or UI |
| **Supervisor** | self-heal orchestration | all agent events | retries, fallbacks, alerts | always-on |

Each agent: `class Agent: name; def handle(event)->[event]; def health()->status;
def fallback(job)`. Register on the bus; communicate only via events.

---

### 6. Hunyuan Video integration (text-to-video + lip-sync)
**Engine (named exactly "Hunyuan Video"):** integrate the open-source
**Hunyuan Video** text-to-video model as a visual source module
`pipelines/common/hunyuan_video.py`. Recommended open runtime: a **ComfyUI**
backend (open-source) driving Hunyuan Video, called over its local HTTP/WebSocket
API — keeps it free, local, and swappable.

**Lip-sync (required):** after Hunyuan Video generates the actor shot, run an
**open-source lip-sync pass** so the generated actor's mouth matches the Kokoro
voiceover (`vo.wav`). Use an open lip-sync model `[FILL: chosen open lip-sync
model, e.g. LatentSync / Wav2Lip / SadTalker / MuseTalk]`; the module exposes one
`lipsync(video, audio)->video` call so the model is replaceable.

**API surface (`hunyuan_video.py`):**
```python
def is_available() -> bool                      # GPU/VRAM + backend reachable
def render(prompt: str, *, seconds: float, fps: int, width: int, height: int,
           seed: int|None, steps: int, actor: str|None,
           progress_cb=None) -> Path             # returns silent mp4 (frames)
def lipsync(video: Path, audio: Path, actor: str|None=None) -> Path
def render_actor_shot(prompt, vo_wav, **kw) -> Path   # render() then lipsync()
```
- Integrates as a selectable visual source in Pipeline A/B (alongside
  `image_gen`/`media_fetch`); the Render Studio + Trigger button drive it.
- Streams progress to the UI via the job/event bus (percent + preview frames).
- **Self-heal:** if `is_available()` is False or render fails validation, fall
  back to `image_gen`/footage and emit `degraded` (never block the pipeline).

---

### 7. Trigger button — implementation & interactions
- **Placement:** primary CTA in Render Studio; secondary on each draft card
  ("Render with Hunyuan Video").
- **State machine:** `idle → submitting → queued → rendering(%) → lip-syncing →
  done | failed | canceled`. Disable while in flight; show progress + ETA;
  `aria-busy` + live-region announcements; cancel sends a stop event to the job.
- **Action:** POST `/render` → Trigger Agent enqueues a Hunyuan Video job →
  WebSocket streams progress/preview frames → on done, the draft's visual source
  is set to the lip-synced clip and re-assembled by FFmpeg.
- **Failure UX:** inline error + **Retry** + "switched to fallback footage" note;
  never a dead end.
- **Keyboard/a11y:** focusable, Enter/Space activate, focus retained on
  completion, result announced.

---

### 8. Animation & UI/UX guidelines
- Motion is **functional**: 150–250ms ease-out for state changes; spring only on
  the Trigger button press. Respect `prefers-reduced-motion` (kill all non-
  essential motion).
- Micro-interactions: button press ripple, progress ring fill, agent-graph edges
  pulse when a message flows, variant cards stagger-in, toast slide+fade.
- Skeletons (not spinners) for lists; preview player does poster → streamed
  frames → final. 60fps target; animate only `transform`/`opacity`; no layout
  thrash (CLS≈0).
- Consistent tokens with existing dashboard; dark/light auto; all states
  (idle/loading/empty/error/degraded) designed.

---

### 9. Open-source licensing & contribution plan
- Repo license: `[FILL: chosen OSI license, e.g. MIT or Apache-2.0]`. Ensure
  compatibility with each dependency's license (qwen weights, Kokoro, Whisper,
  FFmpeg/LGPL-or-GPL build, **Hunyuan Video** model license, chosen lip-sync
  model license, ComfyUI). Record every model/asset license in `state.db` and a
  `THIRD_PARTY_LICENSES.md` (extend the existing asset-license logging).
- Contribution: `CONTRIBUTING.md`, conventional commits, issue/PR templates,
  `ruff`+`pytest` CI, semantic-versioned releases, `CODE_OF_CONDUCT.md`.
- Keep every component swappable behind the existing module interfaces so the
  project stays fully free/open and forkable.

---

### 10. Performance & compatibility
- **Reality check:** full-quality **Hunyuan Video** is GPU-heavy and will *not*
  run smoothly on a typical PC at high res. To honor "runs on a standard PC,"
  the integration must: default to **low-res/short preview** (e.g. 540p, few
  seconds), support **quantized/community builds via ComfyUI** `[FILL: target GPU
  + VRAM, e.g. 8–12GB]`, run rendering **off the UI thread in a job queue**, and
  **degrade to image/footage** when VRAM is insufficient (detected by
  `is_available()`).
- CPU-only / low-VRAM machines: Hunyuan path disabled with a clear UI note;
  pipeline still produces reels via the existing image/footage sources.
- Optional remote render worker is a `[FILL: optional self-hosted GPU endpoint]`
  — not required, must stay open-source if used.
- Targets: UI interactive regardless of render load; render jobs cancellable;
  memory-bounded queue; everything else (script/TTS/subs/FFmpeg) unchanged and
  light.

---

### Open placeholders to fill before build
`[FILL: target audience]` · `[FILL: chosen open lip-sync model]` ·
`[FILL: analytics source for audience feedback]` · `[FILL: OSI license]` ·
`[FILL: target GPU + VRAM]` · `[FILL: optional self-hosted GPU endpoint]` ·
`[FILL: which platforms Auto-Post publishes to]`

---

### Reference example (verbatim from the request brief)
> "the ui is trash show me youre true powers and creativy when it comes to
> desging and coding a ui for the current pipeline and also upgrade a improve the
> pipeline add self correction and self heal and self improvement and also add
> mulit agents each assigns to work like pipeline trigger"
