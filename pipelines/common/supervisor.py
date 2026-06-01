"""Self-correction, self-healing, and self-improvement primitives.

- run_stage(): validated retries with exponential backoff (self-correction),
  then a documented fallback (self-healing) instead of crashing.
- CircuitBreaker: trips an agent after repeated failures so the system degrades
  gracefully rather than hammering a broken dependency.
- priors: a persisted weight store updated from outcome scores (self-improvement)
  used to bias future generation choices. No external ML services.
"""
from __future__ import annotations
import time, random, json, logging
from dataclasses import dataclass, field
from typing import Callable, Any
from . import db, bus

log = logging.getLogger("supervisor")


class StageFailed(Exception):
    pass


@dataclass
class Stage:
    name: str
    execute: Callable[..., Any]                       # (job, attempt) -> output
    validate: Callable[[Any], tuple[bool, str]] = lambda o: (True, "")
    fallback: Callable[..., Any] | None = None        # (job) -> output  (self-heal)
    max_retries: int = 3
    base_delay: float = 0.5
    params_for: Callable[[dict, int], dict] = field(default=lambda job, attempt: {})


def run_stage(stage: Stage, job: dict):
    """Self-correcting execution with retries, then self-healing fallback."""
    job_id = job.get("id")
    last_note = ""
    for attempt in range(stage.max_retries):
        if job_id and bus.is_canceled(job_id):
            raise StageFailed(f"{stage.name}: canceled")
        try:
            out = stage.execute(job, attempt=attempt, **stage.params_for(job, attempt))
            ok, note = stage.validate(out)
            if ok:
                bus.emit(job_id, stage.name, "stage_ok", f"attempt {attempt}")
                return out
            last_note = note
            bus.emit(job_id, stage.name, "self_correct", f"attempt {attempt}: {note}")
        except Exception as e:
            last_note = repr(e)
            bus.emit(job_id, stage.name, "stage_error", f"attempt {attempt}: {e}")
        time.sleep(stage.base_delay * (2 ** attempt) + random.uniform(0, 0.2))

    if stage.fallback:
        bus.emit(job_id, stage.name, "degraded", f"fallback after: {last_note}")
        return stage.fallback(job)
    raise StageFailed(f"{stage.name}: {last_note}")


class CircuitBreaker:
    """Trips OPEN after `threshold` consecutive failures; auto half-opens after cooldown."""
    def __init__(self, name: str, threshold: int = 3, cooldown: float = 30.0):
        self.name, self.threshold, self.cooldown = name, threshold, cooldown
        self.fails = 0
        self.opened_at = 0.0

    @property
    def open(self) -> bool:
        if self.fails < self.threshold:
            return False
        if time.time() - self.opened_at > self.cooldown:   # half-open: allow a probe
            return False
        return True

    def record(self, ok: bool):
        if ok:
            self.fails = 0
        else:
            self.fails += 1
            if self.fails == self.threshold:
                self.opened_at = time.time()
                bus.emit(None, self.name, "circuit_open", f"{self.fails} fails")


def guard(name: str, fn: Callable, *args, breaker: CircuitBreaker | None = None,
          fallback: Callable | None = None, **kwargs):
    """Run fn under a circuit breaker; degrade to fallback when tripped/failing."""
    if breaker and breaker.open:
        bus.emit(None, name, "degraded", "circuit open -> fallback")
        if fallback:
            return fallback(*args, **kwargs)
        raise StageFailed(f"{name}: circuit open and no fallback")
    try:
        out = fn(*args, **kwargs)
        if breaker:
            breaker.record(True)
        return out
    except Exception as e:
        if breaker:
            breaker.record(False)
        bus.emit(None, name, "stage_error", repr(e))
        if fallback:
            return fallback(*args, **kwargs)
        raise


# --------------------------------------------------------------- self-improvement
class Priors:
    """Persisted feature->reward weights. Bandit-style update; biases future choices."""
    KEY = "priors"

    def _load(self) -> dict:
        with db.conn() as c:
            r = c.execute("SELECT v FROM kv WHERE k=?", (self.KEY,)).fetchone()
            return json.loads(r["v"]) if r else {}

    def _save(self, data: dict):
        with db.conn() as c:
            c.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                      (self.KEY, json.dumps(data)))

    def update(self, features: dict, reward: float, lr: float = 0.2):
        data = self._load()
        for k, v in features.items():
            key = f"{k}={v}"
            cur = data.get(key, {"w": 0.0, "n": 0})
            cur["w"] += lr * (reward - cur["w"])   # exponential moving average
            cur["n"] += 1
            data[key] = cur
        self._save(data)
        bus.emit(None, "self_improve", "priors_updated", json.dumps(features))

    def score(self, features: dict) -> float:
        data = self._load()
        return sum(data.get(f"{k}={v}", {"w": 0.0})["w"] for k, v in features.items())

    def weights(self) -> dict:
        return self._load()


priors = Priors()


def record_outcome(features: dict, reward: float):
    """Call after QA / audience feedback / approval to teach the generator."""
    priors.update(features, reward)
