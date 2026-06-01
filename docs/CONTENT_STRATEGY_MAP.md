# Channel Takeaways → Pipeline Features (mapping + implementation)

Each top-5 cross-channel takeaway is mapped to a concrete, implemented feature in
the repo. "Status" = what shipped in this pass.

| # | Takeaway (source channels) | Pipeline feature | Module | Status |
|---|---|---|---|---|
| 1 | **Ship reproducible workflows/assets, not just demos** (pixaroma, Prompt Mastery, Youri) | Per-reel **workflow card**: a sidecar `.workflow.json` + `.md` with script, beats/prompts, voice, mood, music, visual source, render params, and every asset's source+license. | `common/workflow_card.py` | ✅ implemented + wired into Pipeline A/B |
| 2 | **Treat thumbnail/title as a testable system** (MrBeast: one-face/one-object/one-question + big number, variation testing) | **Title/thumbnail variant generator**: N MrBeast-style title + big-number variants per reel; thumbnails composited over a frame; variants stored for CTR-style selection via the audience-feedback → priors loop. | `common/thumbnails.py`, `qwen_client.thumbnail_titles` | ✅ titles implemented + wired into VariantGen agent; thumbnail image needs FFmpeg |
| 3 | **Faceless end-to-end AI production + volume/winner-selection** (Malva AI, Youri) | Already the core pipeline (auto topic→script→TTS→visual→subs→music→export) + weekly batch (21/pipeline) + reject-loop regeneration. Reinforced by #4's winner-selection. | `pipeline_a/b.py`, `batch.py`, `agents.py` | ✅ pre-existing, reinforced |
| 4 | **Trend/search-first topic selection biased by what performs** (AI Search, Youri, zapiwala) | **Topic engine**: over-generate candidates, rank by a pluggable trend hook, and bias generation toward the best-performing category/mood/voice learned in the self-improvement priors. | `common/topic_engine.py`, `qwen_client.seed_topics(profile=…)`, `batch.py` | ✅ implemented + wired into weekly batch |
| 5 | **Build a series + ecosystem** (NetworkChuck, pixaroma) | **Episodes ("epsideos mode")** agent for numbered series; workflow cards (#1) act as the downloadable lead-magnet/asset library. | `agents.py` (EpisodesAgent), `workflow_card.py` | ✅ pre-existing + reinforced by #1 |

## How the self-improvement loop now closes (ties #2 + #4)
1. Each reel records outcome features (category, mood, voice, visual_source) →
   `supervisor.record_outcome` updates `priors` (already in place).
2. `topic_engine.preferred_profile()` reads `priors` to find the best-performing
   category/mood → biases `qwen_client.seed_topics` for next week's batch.
3. `VariantGen` agent produces MrBeast-style title/thumbnail variants; the
   `AudienceFeedback` agent turns engagement into reward → feeds the same priors.
   Net effect: topic choice **and** packaging both drift toward what performs.

## Not implemented here (call-outs, not silent omissions)
- Real **trend/search-volume signal** is a pluggable hook (`trend_fn`) defaulting
  to neutral — wire to `[FILL: trends/search API]` to make #4 demand-driven.
- Real **CTR measurement** needs a publish/analytics integration
  (`[FILL: analytics source]`); the loop is built, the live signal is stubbed.
- Thumbnail **image** compositing requires FFmpeg installed (titles work without it).
