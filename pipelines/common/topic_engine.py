"""Search/priors-first topic selection (takeaway #4).

Instead of picking topics at random, the engine:
  1. reads the self-improvement `priors` to find the best-performing
     category/mood/voice profile (what actually performed), and
  2. ranks candidate topics by a pluggable trend/search-volume hook.

batch.py over-generates candidates biased to the learned profile, then keeps the
top N. The trend hook defaults to neutral; wire it to a real trends/search API
([FILL: trends/search API]) to make selection demand-driven.
"""
from __future__ import annotations
import logging
from typing import Callable
from . import supervisor

log = logging.getLogger("topic_engine")


def preferred_profile() -> dict:
    """Best feature values learned in priors, e.g. {'category':'history','mood':'mysterious'}."""
    weights = supervisor.priors.weights()
    best: dict[str, tuple[str, float]] = {}
    for key, info in weights.items():
        if "=" not in key:
            continue
        feat, val = key.split("=", 1)
        w = info.get("w", 0.0)
        if feat not in best or w > best[feat][1]:
            best[feat] = (val, w)
    profile = {feat: val for feat, (val, w) in best.items() if w > 0}
    if profile:
        log.info("preferred profile from priors: %s", profile)
    return profile


# default neutral trend signal; replace via batch/caller to make demand-driven
def _neutral_trend(_topic: str) -> float:
    return 0.0


def rank_topics(candidates: list[str], trend_fn: Callable[[str], float] | None = None
                ) -> list[tuple[str, float]]:
    """Dedupe + rank candidates by trend score (stable for ties)."""
    trend_fn = trend_fn or _neutral_trend
    seen: set[str] = set()
    scored: list[tuple[str, float]] = []
    for t in candidates:
        key = (t or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        scored.append((t.strip(), float(trend_fn(t))))
    # stable sort: keep generation order among equal scores
    return sorted(scored, key=lambda x: -x[1])


def best_topics(candidates: list[str], n: int,
                trend_fn: Callable[[str], float] | None = None) -> list[str]:
    return [t for t, _ in rank_topics(candidates, trend_fn)][:n]
