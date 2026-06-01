"""Normalize platform metrics into reward scores for learning loop."""
from __future__ import annotations

def compute_reward(metrics: dict, platform: str) -> float:
    """
    Normalize engagement metrics to [0.0, 1.0] reward for supervisor.record_outcome().
    Platforms have different scales; normalize to a common scale.
    """
    if not metrics:
        return 0.0

    if platform == "youtube":
        views = min(metrics.get("views", 0) / 100000.0, 1.0)
        likes = min(metrics.get("likes", 0) / 5000.0, 1.0)
        comments = min(metrics.get("comments", 0) / 500.0, 1.0)
        ctr = min(metrics.get("ctr", 0.0) / 0.08, 1.0)  # 8% CTR is excellent
        return 0.3 * views + 0.3 * likes + 0.2 * comments + 0.2 * ctr

    elif platform == "tiktok":
        views = min(metrics.get("views", 0) / 200000.0, 1.0)
        likes = min(metrics.get("likes", 0) / 10000.0, 1.0)
        shares = min(metrics.get("shares", 0) / 1000.0, 1.0)
        comments = min(metrics.get("comments", 0) / 500.0, 1.0)
        return 0.4 * views + 0.3 * likes + 0.2 * shares + 0.1 * comments

    return 0.0

def features_for_draft(draft: dict) -> dict:
    """Extract features from draft for supervisor.record_outcome()."""
    return {
        "category": draft.get("category", "default"),
        "pipeline": draft.get("pipeline", "A"),
        "topic_length": len(draft.get("topic", "")) / 100.0,  # normalize to ~[0, 1]
        "mood": draft.get("mood", "documentary"),
    }
