"""Autonomous AI agent team: trend research, production, distribution, feedback, code patching."""
from __future__ import annotations
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import logging, time
from .common import (
    bus, db, config, supervisor, trend_research, qwen_client, engagement,
    youtube_api, tiktok_api, qwen_coder,
)
from . import agents, pipeline_a, pipeline_b

log = logging.getLogger("ai_team")

@dataclass
class TrendResearchAgent(agents.Agent):
    """Discovers trending topics via web scraping + Qwen ranking."""

    def __init__(self):
        super().__init__(name="trend_research", subscribes=("trend_cycle_start", "trend_request"))

    def handle(self, event: dict) -> list:
        try:
            # 1. Fetch from all sources in parallel
            raw_trends = trend_research.fetch_all_trends()
            raw_trends = trend_research.deduplicate_topics(raw_trends)

            # 2. Score and rank via Priors
            scored = trend_research.score_and_rank(raw_trends)

            # 3. Top candidates + Qwen expansion
            top = scored[:5]
            if not top:
                log.warning("No trends found; falling back to pure Qwen generation")
                topics = qwen_client.seed_topics(pipeline="A", n=config.TREND_BATCH_SIZE)
            else:
                topics = qwen_client.seed_topics(
                    pipeline="A",
                    n=config.TREND_BATCH_SIZE,
                    profile={"category": top[0].get("category", "default"), "trend": top[0]["topic"]},
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

def ai_team_agents() -> list[agents.Agent]:
    """Return list of AI team agents for registration."""
    return [
        TrendResearchAgent(),
        ProductionOrchestratorAgent(),
        AutoApproveAgent(),
        DistributionAgent(),
        EngagementFeedbackAgent(),
        QwenCoderAgent(),
    ]
