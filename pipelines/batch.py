"""Weekly batch generation + week helpers.

Pre-generates DRAFTS_PER_PIPELINE (21) drafts per pipeline so they are queued and
waiting 'pending' for the Monday-morning Discord approval post.
"""
from __future__ import annotations
import logging, datetime as dt
from .common import config, db, qwen_client, topic_engine
from . import pipeline_a, pipeline_b

log = logging.getLogger("batch")


def iso_week(d: dt.date | None = None) -> str:
    d = d or dt.date.today()
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _produce(pipeline: str, topic: str):
    return pipeline_a.produce(topic) if pipeline == "A" else pipeline_b.produce(topic)


def generate_week(pipeline: str, n: int | None = None, week: str | None = None) -> list[int]:
    db.init()
    n = n or config.DRAFTS_PER_PIPELINE
    week = week or iso_week()
    log.info("Generating %d drafts for pipeline %s (week %s)", n, pipeline, week)
    # Topic engine (takeaway #4): bias to best-performing profile, over-generate, rank.
    profile = topic_engine.preferred_profile()
    candidates = qwen_client.seed_topics(pipeline, n * 2, profile=profile)
    topics = topic_engine.best_topics(candidates, n)
    ids = []
    for i, topic in enumerate(topics, 1):
        try:
            res = _produce(pipeline, topic)
            db.update_draft(res["draft_id"], week=week)
            ids.append(res["draft_id"])
            log.info("  [%s %d/%d] draft %s ok", pipeline, i, n, res["draft_id"])
        except Exception as e:
            log.exception("  [%s %d/%d] FAILED: %s", pipeline, i, n, e)
    return ids


def regenerate_one(pipeline: str, rejected_topic: str, week: str | None = None) -> dict:
    """Reject loop: produce a fresh proposition draft to refill a slot."""
    week = week or iso_week()
    new_topic = qwen_client.new_proposition(pipeline, rejected_topic)
    res = _produce(pipeline, new_topic)
    db.update_draft(res["draft_id"], week=week)
    res["topic"] = new_topic
    return res


def generate_all_weeks() -> dict:
    return {"A": generate_week("A"), "B": generate_week("B")}
