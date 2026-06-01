"""Autonomous AI agent team: trend research, production, distribution, feedback, code patching."""
from __future__ import annotations
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import logging, time
from .common import (
    bus, db, config, supervisor, trend_research, qwen_client, engagement,
    youtube_api, tiktok_api, qwen_coder, ffmpeg_build, sfx,
)
from . import agents, pipeline_a, pipeline_b

# Register human-readable roles for the live dashboard (see agents.ROLES).
agents.ROLES.update({
    "niche_research": ("Selects the best content niche from research signals", "trend_cycle_start / niche_request"),
    "fact_check":     ("Verifies factual claims in each script via Qwen", "production_complete / render_done"),
    "audio_editor":   ("Adds BGM, SFX & audio mastering to the final render", "render_done / production_complete"),
    "reviewer":       ("Reviews every agent's work; proposes redos (gated)", "qa_* / fact_check_result / audio_enhanced"),
})

log = logging.getLogger("ai_team")

@dataclass
class TrendResearchAgent(agents.Agent):
    """Discovers trending topics via web scraping + Qwen ranking."""

    def __init__(self):
        super().__init__(name="trend_research", subscribes=("niche_selected", "trend_request"))

    def handle(self, event: dict) -> list:
        try:
            # 0. The niche researcher (upstream) may have chosen a niche to favor.
            niche = (event.get("data") or {}).get("niche")

            # 1. Fetch from all sources in parallel
            raw_trends = trend_research.fetch_all_trends()
            raw_trends = trend_research.deduplicate_topics(raw_trends)

            # 2. Score and rank via Priors
            scored = trend_research.score_and_rank(raw_trends)

            # 3. Top candidates + Qwen expansion, biased toward the chosen niche
            top = scored[:5]
            profile = {"category": niche} if niche else None
            if not top and not niche:
                log.warning("No trends found; falling back to pure Qwen generation")
                topics = qwen_client.seed_topics(pipeline="A", n=config.TREND_BATCH_SIZE)
            else:
                if top:
                    profile = profile or {}
                    profile.setdefault("category", top[0].get("category", "default"))
                    profile["trend"] = top[0]["topic"]
                topics = qwen_client.seed_topics(
                    pipeline="A", n=config.TREND_BATCH_SIZE, profile=profile,
                )

            # 4. Store in DB
            for topic in topics:
                db.add_trend("qwen_generated", topic, raw_score=0.0, prior_score=0.0)

            # 5. Emit event
            bus.emit(event.get("job_id"), self.name, "topics_ready", data={"topics": topics})
            return [{"topics": topics}]

        except Exception as e:
            log.exception(f"TrendResearchAgent.handle failed: {e}")
            raise

    def fallback(self, event: dict) -> list:
        topics = qwen_client.seed_topics(pipeline="A", n=config.TREND_BATCH_SIZE)
        bus.emit(event.get("job_id"), self.name, "topics_ready", data={"topics": topics})
        return [{"topics": topics}]

@dataclass
class ProductionOrchestratorAgent(agents.Agent):
    """Orchestrates pipeline runs for approved topics."""

    def __init__(self):
        super().__init__(name="production_orchestrator", subscribes=("topics_ready", "production_request"))

    def handle(self, event: dict) -> list:
        topics = event.get("data", {}).get("topics", [])
        results = []

        for topic in topics:
            try:
                # Run pipeline in background thread
                def run_pipeline():
                    try:
                        draft_dict = pipeline_a.produce(topic, visual_source="auto")
                        draft_id = draft_dict.get("draft_id")
                        if draft_id:
                            bus.emit(
                                event.get("job_id"),
                                self.name,
                                "production_complete",
                                data={"draft_id": draft_id, "topic": topic, "pipeline": "A"},
                            )
                            if config.AUTO_APPROVE:
                                bus.emit(None, "ui", "auto_approve_request", data={"draft_id": draft_id})
                    except Exception as e:
                        bus.emit(None, self.name, "production_failed", note=str(e))

                thr = ThreadPoolExecutor(max_workers=1)
                thr.submit(run_pipeline)
                results.append({"topic": topic, "status": "queued"})
            except Exception as e:
                log.error(f"ProductionOrchestratorAgent failed for {topic}: {e}")
                results.append({"topic": topic, "status": "failed", "error": str(e)})

        return results

    def fallback(self, event: dict) -> list:
        # Fallback to Pipeline B
        topics = event.get("data", {}).get("topics", [])
        results = []
        for topic in topics:
            try:
                draft_dict = pipeline_b.produce(topic)
                results.append({"topic": topic, "status": "fallback_b", "draft_id": draft_dict.get("draft_id")})
            except Exception as e:
                results.append({"topic": topic, "status": "failed", "error": str(e)})
        return results

@dataclass
class AutoApproveAgent(agents.Agent):
    """Conditionally auto-approve drafts based on AUTO_APPROVE flag."""

    def __init__(self):
        super().__init__(name="auto_approve", subscribes=("auto_approve_request", "production_complete"))

    def handle(self, event: dict) -> list:
        draft_id = event.get("data", {}).get("draft_id")
        if not draft_id:
            return []

        if config.AUTO_APPROVE:
            db.update_draft(draft_id, status="approved")
            bus.emit(None, "ui", "approved", data={"draft_id": draft_id})
            log.info(f"Auto-approved draft {draft_id}")
            return [{"draft_id": draft_id, "status": "approved"}]
        else:
            bus.emit(None, "ui", "pending_human_review", data={"draft_id": draft_id})
            log.info(f"Draft {draft_id} waiting for human review")
            return [{"draft_id": draft_id, "status": "pending_review"}]

@dataclass
class DistributionAgent(agents.Agent):
    """Publishes approved drafts to YouTube/TikTok."""

    def __init__(self):
        super().__init__(name="distribution", subscribes=("approved", "publish_request"))

    def handle(self, event: dict) -> list:
        draft_id = event.get("data", {}).get("draft_id")
        draft = db.get_draft(draft_id)
        if not draft:
            return []

        results = {}

        # YouTube
        if config.YOUTUBE_CLIENT_ID:
            try:
                yt_id = youtube_api.upload_video(draft)
                if yt_id:
                    db.log_engagement(draft_id, "youtube", yt_id, 0, 0, 0, 0, 0.0, 0.0)
                    results["youtube"] = yt_id
                    log.info(f"Distributed draft {draft_id} to YouTube: {yt_id}")
            except Exception as e:
                log.error(f"YouTube distribution failed: {e}")

        # TikTok
        if config.TIKTOK_CLIENT_KEY:
            try:
                tt_id = tiktok_api.upload_video(draft)
                if tt_id:
                    db.log_engagement(draft_id, "tiktok", tt_id, 0, 0, 0, 0, 0.0, 0.0)
                    results["tiktok"] = tt_id
                    log.info(f"Distributed draft {draft_id} to TikTok: {tt_id}")
            except Exception as e:
                log.error(f"TikTok distribution failed: {e}")

        # Update draft status
        db.update_draft(draft_id, status="published")

        # Emit event for engagement feedback
        bus.emit(None, self.name, "distributed", data={"draft_id": draft_id, **results})

        return [{"draft_id": draft_id, **results}]

    def fallback(self, event: dict) -> list:
        draft_id = event.get("data", {}).get("draft_id")
        if draft_id:
            # Fall back to existing autopost queue
            try:
                from . import autopost
                autopost.queue_draft(draft_id, provider="local_manifest")
                log.info(f"Draft {draft_id} queued via autopost fallback")
            except Exception:
                pass
        return [{"draft_id": draft_id, "fallback": "autopost"}]

@dataclass
class EngagementFeedbackAgent(agents.Agent):
    """Polls platform metrics and feeds rewards into learning loop."""

    def __init__(self):
        super().__init__(name="engagement_feedback", subscribes=("distributed", "engagement_poll"))

    def handle(self, event: dict) -> list:
        event_type = event.get("type")
        draft_id = event.get("data", {}).get("draft_id")

        if event_type == "distributed":
            # Just emitted, poll later
            return []

        if event_type != "engagement_poll":
            return []

        # Get engagement metrics and update DB + priors
        draft = db.get_draft(draft_id)
        if not draft:
            return []

        results = []
        for eng in db.get_engagement_for_draft(draft_id):
            platform = eng.get("platform")
            video_id = eng.get("video_id")

            try:
                if platform == "youtube":
                    metrics = youtube_api.fetch_metrics(video_id)
                elif platform == "tiktok":
                    metrics = tiktok_api.fetch_metrics(video_id)
                else:
                    continue

                if metrics:
                    reward = engagement.compute_reward(metrics, platform)
                    db.log_engagement(draft_id, platform, video_id, **metrics, reward=reward)

                    # Feed into learning loop
                    features = engagement.features_for_draft(draft)
                    supervisor.record_outcome(features, reward)

                    bus.emit(None, self.name, "engagement_scored", data={
                        "draft_id": draft_id,
                        "platform": platform,
                        "metrics": metrics,
                        "reward": reward,
                    })

                    results.append({"platform": platform, "reward": reward, "metrics": metrics})
                    log.info(f"Draft {draft_id} on {platform}: reward={reward:.3f}")
            except Exception as e:
                log.error(f"Engagement polling failed for {draft_id}/{platform}: {e}")

        return results

@dataclass
class QwenCoderAgent(agents.Agent):
    """Generates and applies code patches from errors."""

    def __init__(self):
        super().__init__(name="qwen_coder", subscribes=("agent_error", "stage_error", "circuit_open"))
        self._patch_count = 0

    def handle(self, event: dict) -> list:
        error_data = event.get("data", "")
        if not isinstance(error_data, str):
            return []

        # Extract file and generate patch
        file_path = qwen_coder.extract_file_from_traceback(error_data)
        if not file_path:
            log.warning("Could not extract file from traceback")
            return []

        patch_diff = qwen_coder.generate_patch(file_path, error_data)
        if not patch_diff:
            log.warning(f"Could not generate patch for {file_path}")
            return []

        # Store in DB
        patch_id = db.add_patch(file_path, error_data[:200], patch_diff)
        log.info(f"Generated patch {patch_id} for {file_path}")

        # Emit for dashboard
        bus.emit(None, self.name, "patch_ready", data={
            "patch_id": patch_id,
            "file_path": file_path,
            "patch_diff": patch_diff,
        })

        # Auto-apply if enabled
        if config.AUTO_PATCH:
            self._patch_count += 1
            if self._patch_count > 2:
                log.warning("Patch loop detected; stopping auto-apply")
                bus.emit(None, self.name, "patch_loop_detected")
                return []

            if qwen_coder.apply_patch(patch_diff, file_path):
                db.apply_patch(patch_id)
                bus.emit(None, self.name, "patch_applied", data={"patch_id": patch_id})
                log.info(f"Applied patch {patch_id}")
                return [{"patch_id": patch_id, "applied": True}]
            else:
                log.error(f"Failed to apply patch {patch_id}")

        return [{"patch_id": patch_id, "applied": False}]

@dataclass
class NicheResearchAgent(agents.Agent):
    """Selects the best content niche from trend + prior signals (transparent criteria)."""

    def __init__(self):
        super().__init__(name="niche_research", subscribes=("trend_cycle_start", "niche_request"))

    def handle(self, event: dict) -> list:
        # Build candidate niches from recent trends + learned category priors.
        candidates: list[dict] = []
        seen = set()
        for t in db.top_trends(n=12, unused_only=False):
            cat = (t.get("source") or "trend")
            score = float(t.get("raw_score", 0.0)) + float(t.get("prior_score", 0.0))
            candidates.append({"niche": t.get("topic", ""), "score": score, "source": cat})
        for cat in ("history", "geography", "science", "default"):
            if cat in seen:
                continue
            seen.add(cat)
            try:
                ps = float(supervisor.priors.score({"category": cat}))
            except Exception:
                ps = 0.0
            candidates.append({"niche": cat, "score": ps, "source": "prior"})

        choice = qwen_client.select_niche(candidates)
        niche = choice.get("niche", "default")
        score = float(choice.get("score", 0.0) or 0.0)
        criteria = choice.get("criteria", [])
        db.add_niche(niche, criteria, score)
        bus.emit(event.get("job_id"), self.name, "niche_selected",
                 note=f"{niche} ({score:.2f})",
                 data={"niche": niche, "score": score, "criteria": criteria})
        return [{"niche": niche, "score": score}]

    def fallback(self, event: dict) -> list:
        bus.emit(event.get("job_id"), self.name, "niche_selected",
                 note="default (fallback)", data={"niche": "default", "score": 0.0, "criteria": []})
        return [{"niche": "default"}]


@dataclass
class FactCheckAgent(agents.Agent):
    """Verifies factual claims in a draft's script via Qwen; flags contradictions."""

    def __init__(self):
        super().__init__(name="fact_check",
                         subscribes=("production_complete", "render_done", "fact_check_request"))

    def handle(self, event: dict) -> list:
        data = event.get("data") or {}
        draft_id = data.get("draft_id")
        draft = db.get_draft(draft_id) if draft_id else None
        if not draft:
            return []
        script = draft.get("script") or draft.get("topic") or ""
        if not script.strip():
            return []
        claims = qwen_client.fact_check(script)
        flagged = False
        for c in claims:
            db.add_fact_check(draft_id, c["claim"], c["verdict"], c["rationale"])
            if c["verdict"] == "contradicted":
                flagged = True
        n_bad = sum(1 for c in claims if c["verdict"] == "contradicted")
        bus.emit(event.get("job_id"), self.name, "fact_check_result",
                 note=f"{len(claims)} claims, {n_bad} contradicted",
                 data={"draft_id": draft_id, "claims": claims, "flagged": flagged})
        return [{"draft_id": draft_id, "flagged": flagged, "claims": len(claims)}]


@dataclass
class AudioEditorAgent(agents.Agent):
    """Adds BGM bed + timed SFX and re-masters the finished reel for engagement."""

    def __init__(self):
        super().__init__(name="audio_editor", subscribes=("render_done", "production_complete"))

    def _video_for(self, event: dict) -> tuple:
        data = event.get("data") or {}
        video = data.get("video")
        draft_id = data.get("draft_id")
        if not video and draft_id:
            d = db.get_draft(draft_id)
            video = d.get("video_path") if d else None
        return video, draft_id

    def handle(self, event: dict) -> list:
        from pathlib import Path
        video, draft_id = self._video_for(event)
        if not video or not Path(video).exists():
            return []
        video = Path(video)
        # Guard against re-processing an already-enhanced file.
        if video.stem.endswith("_enhanced"):
            return []
        dur = ffmpeg_build.probe_duration(video)
        if dur <= 0:
            return []
        sfx_paths = sfx.ensure_library()
        cues = sfx.plan_cues(dur)
        out = video.with_name(video.stem + "_enhanced.mp4")
        try:
            ffmpeg_build.enhance_audio(video, cues, sfx_paths, out)
        except Exception as e:
            log.warning("audio enhance failed: %s", e)
            return []
        if draft_id:
            db.log_asset(draft_id, "audio", "local", "", "procedural-sfx", out)
        bus.emit(event.get("job_id"), self.name, "audio_enhanced",
                 note=f"{len(cues)} cues -> {out.name}",
                 data={"draft_id": draft_id, "video": str(out), "cues": len(cues)})
        return [{"draft_id": draft_id, "video": str(out)}]


@dataclass
class ReviewerAgent(agents.Agent):
    """Reviews every agent's output and proposes redos. Gated by config.AUTO_REDO."""

    def __init__(self):
        super().__init__(name="reviewer",
                         subscribes=("qa_pass", "qa_fail", "fact_check_result",
                                     "audio_enhanced", "production_complete", "render_done"))
        self._checks: dict = {}

    def handle(self, event: dict) -> list:
        etype = event.get("type")
        data = event.get("data") or {}
        draft_id = data.get("draft_id") or event.get("job_id") or "unknown"
        rec = self._checks.setdefault(draft_id, {})

        verdict, detail, redo = None, "", False
        if etype in ("production_complete", "render_done"):
            rec["produced"] = True
        elif etype == "qa_pass":
            rec["qa"] = True
        elif etype == "qa_fail":
            rec["qa"] = False
            verdict, detail, redo = "redo", "duration QA failed", True
        elif etype == "fact_check_result":
            rec["fact_ok"] = not data.get("flagged")
            if data.get("flagged"):
                verdict, detail, redo = "redo", "fact-check found a contradiction", True
        elif etype == "audio_enhanced":
            rec["audio"] = True

        if verdict is None:
            # No problem from this event; if the pipeline looks complete, pass it.
            if rec.get("produced") and rec.get("audio") and rec.get("fact_ok", True) and rec.get("qa", True):
                db.add_review("pipeline", draft_id if isinstance(draft_id, int) else None,
                              "pass", "all checks green")
                bus.emit(event.get("job_id"), self.name, "review_passed",
                         note="all checks green", data={"draft_id": draft_id})
                return [{"draft_id": draft_id, "verdict": "pass"}]
            return []

        # A check failed. Record + decide whether to auto-redo (gated) or wait.
        did = int(draft_id) if isinstance(draft_id, int) else None
        db.add_review(etype, did, verdict, detail)
        if redo and config.AUTO_REDO:
            bus.emit(event.get("job_id"), self.name, "redo_request",
                     note=f"auto-redo: {detail}", data={"draft_id": draft_id, "reason": detail})
            return [{"draft_id": draft_id, "verdict": "redo", "auto": True}]
        bus.emit(event.get("job_id"), self.name, "review_pending",
                 note=f"needs approval: {detail}", data={"draft_id": draft_id, "reason": detail})
        return [{"draft_id": draft_id, "verdict": "flag", "auto": False}]


def ai_team_agents() -> list[agents.Agent]:
    """Return list of AI team agents for registration."""
    return [
        NicheResearchAgent(),
        TrendResearchAgent(),
        ProductionOrchestratorAgent(),
        AutoApproveAgent(),
        DistributionAgent(),
        EngagementFeedbackAgent(),
        QwenCoderAgent(),
        FactCheckAgent(),
        AudioEditorAgent(),
        ReviewerAgent(),
    ]
