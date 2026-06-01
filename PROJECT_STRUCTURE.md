# Project Structure

## Directory Organization

```
reel-pipelines/
├── .github/
│   └── workflows/
│       └── deploy.yml              # GitHub Pages auto-deployment
├── .venv/                          # Python virtual environment
├── dashboard/
│   └── index.html                  # Modern reactive UI (1000+ lines)
├── docs/                           # Documentation
├── logs/                           # Runtime logs
├── output/                         # Generated videos
├── drafts/                         # Draft reels
├── music_library/                  # Background music tracks
├── scripts/
│   ├── setup-python.ps1            # Python env setup
│   ├── setup-oauth.ps1             # YouTube/TikTok OAuth
│   ├── install-ffmpeg.ps1          # FFmpeg installer
│   └── ...                         # Other setup scripts
├── pipelines/
│   ├── __init__.py
│   ├── agents.py                   # Agent framework (12 agents)
│   ├── agents_ai_team.py           # AI team agents (6 new)
│   ├── approval_bot.py             # Discord approval bot
│   ├── batch.py                    # Batch generation
│   ├── pipeline_a.py               # Synthetic visuals pipeline
│   ├── pipeline_b.py               # Stock footage pipeline
│   ├── common/
│   │   ├── __init__.py
│   │   ├── db.py                   # SQLite state management
│   │   ├── bus.py                  # Event bus (12 agents)
│   │   ├── config.py               # Configuration + env vars
│   │   ├── supervisor.py           # Circuit breaker + Priors
│   │   ├── trend_research.py       # Trend discovery (6 functions)
│   │   ├── engagement.py           # Engagement metrics + rewards
│   │   ├── qwen_coder.py           # Code patch generation
│   │   ├── youtube_api.py          # YouTube Data API v3
│   │   ├── tiktok_api.py           # TikTok Content Posting API
│   │   ├── qwen_client.py          # Local Qwen LLM interface
│   │   ├── kokoro_tts.py           # Voice synthesis
│   │   ├── whisper_timing.py       # Word-level timestamps
│   │   ├── subtitles.py            # Caption generation
│   │   ├── media_fetch.py          # Stock footage APIs
│   │   ├── image_gen.py            # Image generation
│   │   ├── music.py                # Music selection
│   │   ├── ffmpeg_build.py         # Video assembly
│   │   ├── hunyuan_video.py        # T2V generation
│   │   ├── quality.py              # QA checks
│   │   ├── workflow_card.py        # Metadata card
│   │   ├── thumbnails.py           # Thumbnail generation
│   │   └── autopost.py             # Auto-publishing
├── state.db                        # SQLite database
├── server.py                       # FastHTTP API server (80 lines)
├── run.py                          # CLI entrypoint
├── requirements.txt                # Python dependencies
├── AI_TEAM_README.md               # AI team documentation
├── MRBEAST_PRODUCTION_PIPELINE.md  # Team workflow guide
├── AI_TEAM_README.md               # System architecture
├── DEPLOYMENT.md                   # Deployment guide
├── CLAUDE.md                       # Development guidelines
└── verify_build.py                 # Build verification script
```

## Database Schema (SQLite)

```
drafts                 # Video drafts + metadata
├── id, pipeline, topic, category, title, script
├── video_path, thumb_path, status
├── discord_msg, week, scheduled_for
└── created_at, updated_at

kv                     # Key-value store
├── voice_cursor (round-robin state)
└── priors (learning weights)

assets                 # Media license tracking
├── draft_id, kind (footage|image|music)
├── source (archive.org|pixabay|pexels)
├── url, license, local_path

trend_candidates       # Discovered trending topics
├── source (reddit|youtube_rss|google_trends)
├── topic, raw_score, prior_score
├── used (boolean), created_at

engagement_metrics     # Platform performance data
├── draft_id, platform (youtube|tiktok)
├── video_id, views, likes, comments, shares
├── ctr, reward, fetched_at

platform_tokens        # OAuth credentials
├── platform (youtube|tiktok), access_token
├── refresh_token, expires_at, scope

code_patches           # Qwen Coder generated fixes
├── file_path, error_summary
├── patch_diff (unified diff), applied (boolean)
```

## API Endpoints (12 Total)

### Existing (9)
- GET `/api/health` — System health
- GET `/api/agents` — Agent status
- GET `/api/drafts` — Video list
- GET `/api/jobs` — Job tracking
- GET `/api/events` — Event log
- POST `/api/render` — Trigger production
- POST `/api/approve` — Approve draft
- POST `/api/reject` — Reject draft
- POST `/api/autopost/status` — Publishing status

### New (3)
- GET `/api/trends` — Trending topics
- GET `/api/engagement` — Platform metrics
- GET `/api/patches` — Code patches
- POST `/api/trend_cycle/run` — Manual trend cycle
- POST `/api/distribute/{id}` — Manual distribution
- POST `/api/patches/{id}/apply` — Apply code patch

## AI Agents (12 Total)

### Original (6)
1. **TriggerAgent** — Creates render jobs from UI
2. **VisualQAAgent** — Validates reel duration
3. **AudienceFeedbackAgent** — Scores engagement
4. **AutoPostAgent** — Publishes approved drafts
5. **VariantGenAgent** — Creates thumbnail variants
6. **EpisodesAgent** — Series reproduction

### AI Team (6 New)
1. **TrendResearchAgent** — Discovers trending topics
2. **ProductionOrchestratorAgent** — Runs pipelines
3. **AutoApproveAgent** — Conditional approval
4. **DistributionAgent** — YouTube + TikTok posting
5. **EngagementFeedbackAgent** — Metrics collection
6. **QwenCoderAgent** — Error detection + patching

## CLI Commands

```bash
py run.py a "topic"          # Single Pipeline A reel
py run.py b "topic"          # Single Pipeline B reel
py run.py batch              # Weekly batch (21 per pipeline)
py run.py bot                # Discord approval bot
py run.py serve              # Dashboard + API server
py run.py check              # Environment verification
py run.py ai-team            # Full autonomous system
py run.py trend              # Manual trend research
py run.py distribute <id>    # Manual distribution
py run.py oauth youtube|tiktok  # OAuth setup
```

## Configuration (.env)

```
# Core
OPENAI_API_BASE=http://localhost:11434/v1
OPENAI_API_KEY=ollama
QWEN_MODEL=qwen2.5:7b-instruct
QWEN_CODER_MODEL=qwen2.5-coder:7b-instruct

# APIs
PEXELS_KEY=...
PIXABAY_KEY=...
YOUTUBE_CLIENT_ID=...
YOUTUBE_CLIENT_SECRET=...
YOUTUBE_CHANNEL_ID=...
TIKTOK_CLIENT_KEY=...
TIKTOK_CLIENT_SECRET=...

# Scheduler
TREND_CYCLE_HOURS=24
ENGAGEMENT_POLL_HOURS=6
TREND_BATCH_SIZE=3

# Autonomy
AUTO_APPROVE=false
AUTO_PATCH=false

# Other
FFMPEG_BIN=ffmpeg
FFPROBE_BIN=ffprobe
DISCORD_BOT_TOKEN=...
REEL_API_KEY=...
```

## File Statistics

- **Python files**: 36
- **Lines of code**: ~8,000 (core pipelines + agents)
- **Dashboard**: 1,000+ lines (HTML/CSS/JS)
- **Database tables**: 7
- **API endpoints**: 12
- **AI agents**: 12
- **CLI commands**: 10+

## Key Technologies

- **Language**: Python 3.11+
- **LLM**: Qwen via Ollama/vLLM
- **TTS**: Kokoro (local)
- **Video Gen**: Hunyuan Video (ComfyUI)
- **Stock Media**: Pixabay, Pexels, Archive.org
- **Database**: SQLite3
- **Server**: stdlib FastHTTP
- **Discord**: discord.py + APScheduler
- **UI**: HTML5 + CSS3 + Vanilla JS
- **Platform APIs**: YouTube Data API v3, TikTok Content Posting API v2
- **Event Bus**: Custom (non-framework)

## Deployment

- **Local**: `py run.py ai-team` → http://127.0.0.1:8787
- **Cloud**: GitHub Pages (dashboard) + local API
- **Platform**: Windows/Linux workstation (GPU optional)
