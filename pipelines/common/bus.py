"""Lightweight sqlite-backed job/event bus + in-process async dispatch.

Agents communicate ONLY through events here. Everything is logged, jobs carry
idempotent ids, and the schema is intentionally simple so it can later be
swapped for Redis/NATS without touching agent code.
"""
from __future__ import annotations
import json, time, uuid, logging, threading
from typing import Callable
from . import db

log = logging.getLogger("bus")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    payload    TEXT,                 -- json
    status     TEXT NOT NULL DEFAULT 'queued', -- queued|running|done|failed|degraded|quarantined|canceled
    attempts   INTEGER NOT NULL DEFAULT 0,
    result     TEXT,
    error      TEXT,
    created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     TEXT, agent TEXT, type TEXT, note TEXT, data TEXT, ts REAL
);
"""

_subscribers: dict[str, list[Callable]] = {}
_lock = threading.Lock()


def init():
    db.init()
    with db.conn() as c:
        c.executescript(_SCHEMA)


# ----------------------------------------------------------------- jobs
def new_job(kind: str, payload: dict, job_id: str | None = None) -> str:
    """Create (idempotently) a job. Re-using a job_id returns the existing one."""
    job_id = job_id or f"{kind}-{uuid.uuid4().hex[:12]}"
    now = time.time()
    with db.conn() as c:
        exists = c.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone()
        if exists:
            return job_id
        c.execute("INSERT INTO jobs(id,kind,payload,created_at,updated_at) VALUES(?,?,?,?,?)",
                  (job_id, kind, json.dumps(payload), now, now))
    emit(job_id, "bus", "job_created", kind)
    return job_id


def set_status(job_id: str, status: str, *, result=None, error=None, bump=False):
    with db.conn() as c:
        cur = "attempts = attempts + 1," if bump else ""
        c.execute(f"UPDATE jobs SET status=?, {cur} result=COALESCE(?,result), "
                  "error=COALESCE(?,error), updated_at=? WHERE id=?",
                  (status, json.dumps(result) if result is not None else None,
                   error, time.time(), job_id))


def get_job(job_id: str) -> dict | None:
    with db.conn() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(r) if r else None


def is_canceled(job_id: str) -> bool:
    j = get_job(job_id)
    return bool(j and j["status"] == "canceled")


def cancel(job_id: str):
    set_status(job_id, "canceled")
    emit(job_id, "bus", "canceled", "user/abort")


# ----------------------------------------------------------------- events
def emit(job_id: str | None, agent: str, type_: str, note: str = "", data: dict | None = None):
    ts = time.time()
    with db.conn() as c:
        c.execute("INSERT INTO events(job_id,agent,type,note,data,ts) VALUES(?,?,?,?,?,?)",
                  (job_id, agent, type_, note, json.dumps(data) if data else None, ts))
    log.debug("[%s] %s/%s %s", job_id, agent, type_, note)
    # fan out to in-proc subscribers (synchronous, best-effort)
    with _lock:
        cbs = list(_subscribers.get(type_, [])) + list(_subscribers.get("*", []))
    for cb in cbs:
        try:
            cb({"job_id": job_id, "agent": agent, "type": type_, "note": note, "data": data, "ts": ts})
        except Exception:
            log.exception("subscriber for %s failed", type_)


def subscribe(event_type: str, callback: Callable):
    with _lock:
        _subscribers.setdefault(event_type, []).append(callback)


def unsubscribe(event_type: str, callback: Callable):
    """Remove a previously-registered callback (SSE clients call this on disconnect)."""
    with _lock:
        lst = _subscribers.get(event_type)
        if lst and callback in lst:
            lst.remove(callback)


def recent_events(job_id: str | None = None, limit: int = 50) -> list[dict]:
    q = "SELECT * FROM events"
    args: list = []
    if job_id:
        q += " WHERE job_id=?"; args.append(job_id)
    q += " ORDER BY id DESC LIMIT ?"; args.append(limit)
    with db.conn() as c:
        return [dict(r) for r in c.execute(q, args).fetchall()]
