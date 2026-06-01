"""Cooperating agents that operate over the event bus.

Each agent has: name, handle(event)->[events], health()->status, and an optional
fallback(). Agents subscribe to bus event types and react. They are intentionally
lightweight and degrade gracefully so the system self-heals rather than crashes.

Agents:
  TriggerAgent          - creates render jobs (UI button / cron / reject loop)
  VisualQAAgent         - pass/fail a finished reel (duration vs voiceover)
  AudienceFeedbackAgent - turns engagement signals into scores -> self-improve
  AutoPostAgent         - publishes/schedules a draft AFTER user approval
  VariantGenAgent       - makes N viral variants of an approved draft
  EpisodesAgent         - series + reproduce episodes ("epsideos mode")
  Supervisor wrapper lives in common/supervisor.py and guards every agent.
"""
from __future__ import annotations
import logging, datetime as dt
from dataclasses import dataclass, field
from .common import bus, db, qwen_client, supervisor, ffmpeg_build, config, thumbnails, autopost

log = logging.getLogger("agents")


# Human-readable role + "what it waits for", surfaced live in the dashboard so
# the UI can show what each agent does / did / will do next (not just a status dot).
ROLES: dict[str, tuple[str, str]] = {
    "trigger":        ("Creates render jobs from UI / cron / reject loop", "render_request"),
    "visual_qa":      ("Checks a finished reel's duration vs. its voiceover", "render_done"),
    "audience_feedback": ("Turns engagement signals into a learning reward", "published / feedback"),
    "auto_post":      ("Queues an approved draft for publishing", "approved"),
    "variant_gen":    ("Builds viral title/thumbnail packaging variants", "qa_pass / make_variants"),
    "episodes":       ("Generates and reproduces series episodes", "new_episode"),
    "trend_research": ("Discovers + ranks trending topics", "niche_selected / trend_cycle_start"),
    "production_orchestrator": ("Runs Pipeline A/B for chosen topics", "topics_ready"),
    "auto_approve":   ("Approves drafts (auto or human-gated)", "production_complete"),
    "distribution":   ("Publishes approved drafts to YouTube/TikTok", "approved / publish_request"),
    "engagement_feedback": ("Polls platform metrics, feeds the learning loop", "distributed / engagement_poll"),
    "qwen_coder":     ("Generates code patches from errors", "agent_error / stage_error"),
}


@dataclass
class Agent:
    name: str
    subscribes: tuple[str, ...] = ()
    status: str = "idle"
    last_run: float | None = None
    breaker: supervisor.CircuitBreaker = field(default=None)
    role: str = ""
    waits_for: str = ""
    last_action: dict | None = None   # {type, note, ts} of the most recent handled event

    def __post_init__(self):
        if self.breaker is None:
            self.breaker = supervisor.CircuitBreaker(self.name)
        if not self.role or not self.waits_for:
            r, w = ROLES.get(self.name, ("", ", ".join(self.subscribes)))
            self.role = self.role or r
            self.waits_for = self.waits_for or w

    def handle(self, event: dict) -> list[dict]:
        return []

    def health(self) -> dict:
        return {"name": self.name, "status": self.status,
                "last_run": self.last_run, "circuit_open": self.breaker.open,
                "role": self.role, "waits_for": self.waits_for,
                "last_action": self.last_action}

    def fallback(self, event: dict):
        return None

    def _summarize(self, event: dict, out) -> str:
        """One-line 'what it just did' for the live feed."""
        note = event.get("note") or ""
        if isinstance(out, list) and out:
            first = out[0]
            if isinstance(first, dict):
                note = note or first.get("type") or first.get("status") or ""
        return str(note)[:160]

    # called by the runner
    def _dispatch(self, event: dict):
        import time
        self.status = "running"; self.last_run = time.time()
        try:
            out = supervisor.guard(self.name, self.handle, event,
                                   breaker=self.breaker, fallback=self.fallback)
            self.last_action = {"type": event.get("type", ""),
                                "note": self._summarize(event, out),
                                "ts": time.time()}
            self.status = "healing" if self.breaker.open else "idle"
            return out or []
        except Exception as e:
            self.status = "failed"
            self.last_action = {"type": event.get("type", ""),
                                "note": f"error: {e!r}"[:160], "ts": time.time()}
            bus.emit(event.get("job_id"), self.name, "agent_error", repr(e))
            return []


# --------------------------------------------------------------- agents
class TriggerAgent(Agent):
    def __init__(self):
        super().__init__("trigger", subscribes=("render_request",))

    def handle(self, event):
        p = event.get("data") or {}
        pipeline = (p.get("pipeline") or "A").upper()
        kind = "reel_A" if pipeline == "A" else "reel_B"
        job_id = bus.new_job(kind, {"topic": p.get("topic", ""),
                                    "visual_source": p.get("visual_source", "auto"),
                                    "pipeline": pipeline})
        bus.emit(job_id, self.name, "job_enqueued", p.get("topic", ""))
        return [{"type": "job_enqueued", "job_id": job_id}]


class VisualQAAgent(Agent):
    def __init__(self):
        super().__init__("visual_qa", subscribes=("render_done",))

    def handle(self, event):
        d = event.get("data") or {}
        video, target = d.get("video"), d.get("target_dur", 0)
        if not video:
            return []
        dur = ffmpeg_build.probe_duration(video)
        ok = dur > 0.5 and (not target or abs(dur - target) / target <= 0.15)
        bus.emit(event.get("job_id"), self.name, "qa_pass" if ok else "qa_fail",
                 f"{dur:.1f}s vs {target:.1f}s")
        return [{"type": "qa_pass" if ok else "qa_fail", "job_id": event.get("job_id")}]


class AudienceFeedbackAgent(Agent):
    """Turns engagement signals into a reward and teaches the self-improvement priors.
    Real signal source is [FILL: analytics source]; here it reads provided metrics."""
    def __init__(self):
        super().__init__("audience_feedback", subscribes=("published", "feedback"))

    def handle(self, event):
        d = event.get("data") or {}
        metrics = d.get("metrics", {})
        # simple reward: normalized watch-through + reaction rate
        reward = min(1.0, 0.6 * metrics.get("watch_through", 0) + 0.4 * metrics.get("reaction_rate", 0))
        feats = d.get("features", {})
        if feats:
            supervisor.record_outcome(feats, reward)
        bus.emit(event.get("job_id"), self.name, "scored", f"reward={reward:.2f}")
        return [{"type": "scored", "reward": reward}]


class AutoPostAgent(Agent):
    """Queues an approved draft for automated publishing."""
    def __init__(self):
        super().__init__("auto_post", subscribes=("approved",))

    def handle(self, event):
        d = event.get("data") or {}
        draft_id = d.get("draft_id")
        draft = db.get_draft(draft_id) if draft_id else None
        if not draft:
            return []
        publish_job = autopost.queue_draft(int(draft_id))
        bus.emit(event.get("job_id"), self.name, "publish_queued", f"publish_job={publish_job}")
        return [{"type": "publish_queued", "draft_id": draft_id, "publish_job": publish_job}]


class VariantGenAgent(Agent):
    """Creates N viral variants (hook/caption/pacing/thumbnail) of an approved draft."""
    def __init__(self, n: int = 3):
        super().__init__("variant_gen", subscribes=("qa_pass", "make_variants"))
        self.n = n

    def handle(self, event):
        d = event.get("data") or {}
        draft_id = d.get("draft_id")
        draft = db.get_draft(draft_id) if draft_id else None
        if not draft:
            return []
        # MrBeast-style title/thumbnail packaging variants (takeaway #2)
        packs = thumbnails.title_variants(draft.get("topic", ""), draft.get("title", ""), self.n)
        base = round(supervisor.priors.score({"category": draft.get("category")}), 3)
        variants = []
        for i, p in enumerate(packs):
            variants.append({"title": p.get("title"), "big_number": p.get("big_number"),
                             "object": p.get("object"),
                             "pacing": ["fast", "medium", "punchy"][i % 3], "score": base})
        bus.emit(event.get("job_id"), self.name, "variants_made",
                 f"{len(variants)} title/thumbnail variants")
        return [{"type": "variants_made", "draft_id": draft_id, "variants": variants}]


class EpisodesAgent(Agent):
    """Series manager: generate sequential episodes and reproduce them ('epsideos mode')."""
    def __init__(self):
        super().__init__("episodes", subscribes=("new_episode", "reproduce_episode"))

    def handle(self, event):
        d = event.get("data") or {}
        series = d.get("series", "Untitled Series")
        n = d.get("episode", 1)
        spec = qwen_client.script_for_topic(f"{series} — Episode {n}")
        draft_id = db.add_draft("A", f"{series} E{n:02d}", spec["category"],
                                f"{series} · E{n:02d}: {spec['title']}", spec["full_script"])
        bus.emit(None, self.name, "episode_created", f"{series} E{n:02d} (draft {draft_id})")
        return [{"type": "episode_created", "draft_id": draft_id, "series": series, "episode": n}]


# --------------------------------------------------------------- runner
class AgentRunner:
    """Registers agents on the bus and exposes their health for the UI."""
    def __init__(self, agents: list[Agent] | None = None):
        self.agents = agents or default_agents()
        for ag in self.agents:
            for etype in ag.subscribes:
                bus.subscribe(etype, ag._dispatch)

        # Initialize scheduler for AI team cycles
        self._scheduler = None
        self._init_scheduler()

    def _init_scheduler(self):
        """Start APScheduler for trend cycles and engagement polling."""
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            self._scheduler = BackgroundScheduler()

            # Trend research cycle
            self._scheduler.add_job(
                lambda: bus.emit(None, "scheduler", "trend_cycle_start"),
                "interval",
                hours=config.TREND_CYCLE_HOURS,
                id="trend_cycle",
            )

            # Engagement polling cycle
            self._scheduler.add_job(
                self._poll_engagement,
                "interval",
                hours=config.ENGAGEMENT_POLL_HOURS,
                id="engagement_poll",
            )

            self._scheduler.start()
            log.info(f"Scheduler started: trend_cycle every {config.TREND_CYCLE_HOURS}h, engagement_poll every {config.ENGAGEMENT_POLL_HOURS}h")
        except ImportError:
            log.warning("APScheduler not installed; scheduler disabled")
        except Exception as e:
            log.error(f"Scheduler init failed: {e}")

    def _poll_engagement(self):
        """Emit engagement_poll events for drafts that need refreshing."""
        import time as time_mod
        cutoff = time_mod.time() - (config.ENGAGEMENT_POLL_HOURS * 3600)
        with db.conn() as c:
            rows = c.execute(
                "SELECT DISTINCT draft_id FROM engagement_metrics WHERE fetched_at < ?",
                (cutoff,),
            ).fetchall()
        for row in rows:
            draft_id = row[0]
            bus.emit(None, "scheduler", "engagement_poll", data={"draft_id": draft_id})

    def health(self) -> list[dict]:
        return [a.health() for a in self.agents]


# Import AI team agents (after Agent class is defined to avoid circular import)
from . import agents_ai_team


def default_agents() -> list[Agent]:
    return [TriggerAgent(), VisualQAAgent(), AudienceFeedbackAgent(),
            AutoPostAgent(), VariantGenAgent(), EpisodesAgent()] + agents_ai_team.ai_team_agents()


# module-level singleton runner (created on import for convenience)
_runner = None


def get_runner() -> AgentRunner:
    global _runner
    if _runner is None:
        bus.init()
        _runner = AgentRunner()
    return _runner
