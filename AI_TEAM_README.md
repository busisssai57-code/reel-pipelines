# Autonomous AI MrBeast Production Team

**A fully autonomous video production system powered by local AI agents, no human intervention required.**

## Overview

This system runs 6 independent AI agents that collaborate to discover trending topics, generate videos, publish to platforms, and improve themselves through engagement metrics feedback. Everything is local-first (Qwen LLM, FFmpeg, Kokoro TTS) with optional YouTube/TikTok distribution.

## Architecture

### Core Components

**6 AI Agents (event-driven, on the bus)**
1. **TrendResearchAgent** — Runs daily, fetches Reddit/YouTube/Google Trends, ranks by Priors, proposes topics
2. **ProductionOrchestratorAgent** — Takes topics → runs Pipeline A/B in parallel → emits production_complete
3. **AutoApproveAgent** — Conditionally approves drafts (human/auto controlled by `AUTO_APPROVE` flag)
4. **DistributionAgent** — Posts approved videos to YouTube Data API v3 + TikTok Content Posting API
5. **EngagementFeedbackAgent** — Polls platform metrics every 6h, computes rewards, updates Priors for learning
6. **QwenCoderAgent** — Watches for errors, generates patches with Qwen Coder, auto-applies if `AUTO_PATCH=true`

**Database (SQLite, state.db)**
- `trend_candidates` — Discovered topics + raw/prior scores
- `engagement_metrics` — Views/likes/comments/reward per video per platform
- `platform_tokens` — OAuth access/refresh tokens for YouTube + TikTok
- `code_patches` — Generated diffs from QwenCoder (pending/applied status)
- (3 original tables: drafts, assets, kv)

**Event Bus** — All agents communicate via bus.emit(). Scheduler fires `trend_cycle_start` every 24h, `engagement_poll` every 6h.

**Learning Loop** — Engagement rewards feed into `supervisor.Priors`, biasing future `qwen_client.seed_topics()` toward high-performing categories.

## Setup

### 1. Environment & Dependencies
```bash
.\scripts\setup-python.ps1 -Recreate
pip install -r requirements.txt
```

### 2. OAuth Setup (for YouTube/TikTok publishing)
```bash
py run.py oauth youtube    # Guides through Google OAuth consent
py run.py oauth tiktok     # Guides through TikTok OAuth setup
```

This stores tokens securely in `platform_tokens` table.

### 3. Configuration (.env)

Required for autonomous operation:
```
# LLM
OPENAI_API_BASE=http://localhost:11434/v1
QWEN_MODEL=qwen2.5:7b-instruct
QWEN_CODER_MODEL=qwen2.5-coder:7b-instruct

# YouTube OAuth (get from Google Cloud Console)
YOUTUBE_CLIENT_ID=...
YOUTUBE_CLIENT_SECRET=...
YOUTUBE_CHANNEL_ID=...

# TikTok API (get from TikTok for Developers)
TIKTOK_CLIENT_KEY=...
TIKTOK_CLIENT_SECRET=...

# Autonomy controls (false = human in loop, true = fully autonomous)
AUTO_APPROVE=false        # Set to true for automatic draft approval
AUTO_PATCH=false          # Set to true for automatic code patching

# Scheduler intervals
TREND_CYCLE_HOURS=24      # How often to discover new trends
ENGAGEMENT_POLL_HOURS=6   # How often to fetch platform metrics
TREND_BATCH_SIZE=3        # How many videos to produce per cycle

# Other
PEXELS_KEY=...
PIXABAY_KEY=...
FFMPEG_BIN=ffmpeg
```

## Running

### Full Autonomous System
```bash
py run.py ai-team
# Starts dashboard at http://127.0.0.1:8787
# Agents run on schedule + via dashboard controls
```

### Manual Controls
```bash
py run.py trend           # Manually run trend research once
py run.py trend --run     # Run full cycle: trend → produce → queue
py run.py distribute <id> # Manually publish draft to YouTube/TikTok
py run.py oauth youtube   # Re-setup OAuth if token expired
```

## Dashboard

Access at **http://127.0.0.1:8787** when `py run.py ai-team` is running.

### Views

| View | Purpose |
|------|---------|
| **Dashboard** | Stats, pipeline health, recent videos, agent pulse |
| **Review Queue** | Pending drafts (if `AUTO_APPROVE=false`) |
| **Render Studio** | Live progress of video generation |
| **Agents** | Health/status of 6 original agents + 6 AI team agents |
| **Variant Lab** | MrBeast-style thumbnail packaging variants |
| **Episodes** | Series management |
| **Schedule** | Weekly publish calendar |
| **Settings** | API keys, LLM endpoint, Discord config |
| **AI Team** ⭐ | Live status of all 6 AI agents |
| **Trends** ⭐ | Discovered trending topics, produce buttons |
| **Engagement** ⭐ | Platform metrics per published video |
| **Patches** ⭐ | Code patches from Qwen Coder, apply buttons |

⭐ = New for autonomous team

### Controls

- **Run Trend Cycle Now** — Manually trigger trend research
- **Produce** (in Trends view) — Queue a specific trend for video generation
- **Apply** (in Patches view) — Apply a generated code patch
- **Keyboard shortcuts** — A=approve, R=reject (in Review Queue)

## Workflow

### Daily Autonomous Loop

1. **00:00 UTC** — Scheduler emits `trend_cycle_start`
2. **TrendResearchAgent** — Fetches Reddit/YouTube/Google, scores via Priors, proposes 3 topics
3. **ProductionOrchestratorAgent** — Runs Pipeline A/B in parallel for each topic
4. **AutoApproveAgent** — Auto-approves (if `AUTO_APPROVE=true`) or waits for human (review queue)
5. **DistributionAgent** — Posts to YouTube/TikTok, stores video_ids
6. **Engagement polling** (every 6h) — Fetches views/likes/comments, computes rewards
7. **EngagementFeedbackAgent** — Updates Priors with rewards → biases next trend cycle

### Error Recovery

- **Stage failure** → `supervisor.run_stage()` retries with exponential backoff
- **API errors** → Fallback to local manifest or skip gracefully
- **Code crash** → QwenCoderAgent detects, generates patch, optionally applies
- **Circuit breaker** — Trips after 3 failures, prevents cascading collapse

## Performance Targets

| Metric | Target |
|--------|--------|
| Trend discovery | < 30 seconds (parallel web scrape) |
| Video production | 30-35 seconds (one reel) |
| Platform posting | < 5 minutes (OAuth token refresh + upload) |
| Metric polling | < 10 seconds (3 API calls in parallel) |
| Dashboard refresh | 3.5 second poll cycle |

## Customization

### Adding a New Data Source to Trend Research
Edit `pipelines/common/trend_research.py`:
```python
def fetch_your_source():
    # Your code
    return [{"topic": str, "raw_score": float, "source": str}]

# Call in fetch_all_trends():
results.extend(fetch_your_source())
```

### Changing Engagement Reward Formula
Edit `pipelines/common/engagement.py:compute_reward()`:
```python
# YouTube: customize the 0.3/0.3/0.2/0.2 weights
reward = 0.5 * views + 0.3 * likes + 0.2 * comments
```

### Adding a New Agent
Create in `pipelines/agents_ai_team.py`:
```python
@dataclass
class MyAgent(Agent):
    def __init__(self):
        super().__init__(name="my_agent", subscribes=("event_type",))
    
    def handle(self, event):
        # Logic
        bus.emit(None, self.name, "my_result", data={...})
        return [...]

# Register in ai_team_agents():
return [...existing agents..., MyAgent()]
```

## Monitoring

### Logs
```bash
# Check agent events
tail -f logs/  # Events from bus
grep "ai_team" logs/*.log  # Only AI team
```

### Database Queries
```bash
# Top performing topics
select topic, avg(reward) as avg_reward from engagement_metrics 
  group by topic order by avg_reward desc;

# Pending patches
select * from code_patches where applied=0;

# Platform distribution
select platform, count(*) from engagement_metrics group by platform;
```

### Real-time Dashboard
- **AI Team view** shows live agent status + last event
- **Engagement view** shows reward scores and trending metrics
- **Patches view** shows pending fixes with diff preview

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `AUTO_APPROVE` producing low-quality videos | Set to `false`, manually review in dashboard |
| OAuth token expired | Run `py run.py oauth youtube` to refresh |
| Trend cycle not firing | Check APScheduler installed: `pip install APScheduler` |
| Qwen Coder patches breaking code | Set `AUTO_PATCH=false`, review diffs in dashboard |
| No YouTube/TikTok distribution | Verify OAuth tokens: `select * from platform_tokens` |
| Slow engagement polling | Check network, increase `ENGAGEMENT_POLL_HOURS` to 12h |

## Example: Fully Autonomous Setup

1. **Create .env with all OAuth tokens and `AUTO_APPROVE=true`, `AUTO_PATCH=true`**
2. **Run:** `py run.py ai-team`
3. **Open dashboard:** Watch agents work 24/7
4. **No human intervention required** — System discovers, produces, publishes, improves, fixes itself

## Example: Human-in-Loop Setup

1. **Create .env with `AUTO_APPROVE=false`, `AUTO_PATCH=false`**
2. **Run:** `py run.py ai-team`
3. **Monitor Trends view** — See discovered topics in real-time
4. **Review Queue** — Approve/reject each draft before publishing
5. **Patches view** — Review and apply code fixes
6. **Engagement view** — Monitor performance feedback

---

**Built on:** Qwen LLM, Kokoro TTS, Whisper, Hunyuan Video, FFmpeg, SQLite, APScheduler  
**Deployment:** Local Windows/Linux workstation (GPU optional)  
**Distribution:** YouTube Data API v3 + TikTok Content Posting API v2  
**Learning:** Priors bandit via engagement metrics → topic/category optimization
