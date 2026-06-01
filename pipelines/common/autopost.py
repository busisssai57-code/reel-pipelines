"""Auto-poster queue and provider adapters.

The queue is durable in SQLite. The default provider writes a local manifest so
the whole publish workflow can be validated without leaking credentials; setting
AUTOPOST_MODE=webhook sends the same payload to a user-controlled endpoint.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib import request

from . import bus, config, db


SCHEMA = """
CREATE TABLE IF NOT EXISTS publish_jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id      INTEGER NOT NULL,
    provider      TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'queued',
    payload       TEXT,
    response      TEXT,
    scheduled_for TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
"""


def init() -> None:
    db.init()
    with db.conn() as c:
        c.executescript(SCHEMA)


def queue_draft(draft_id: int, provider: str | None = None) -> int:
    """Queue an approved draft for automated publishing."""
    init()
    draft = db.get_draft(draft_id)
    if not draft:
        raise ValueError(f"draft {draft_id} not found")
    provider = provider or config.AUTOPOST_MODE
    payload = _payload_for(draft)
    now = time.time()
    with db.conn() as c:
        existing = c.execute(
            "SELECT id FROM publish_jobs WHERE draft_id=? AND status IN ('queued','running')",
            (draft_id,),
        ).fetchone()
        if existing:
            return int(existing["id"])
        cur = c.execute(
            "INSERT INTO publish_jobs(draft_id,provider,status,payload,scheduled_for,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (draft_id, provider, "queued", json.dumps(payload), draft.get("scheduled_for"), now, now),
        )
        job_id = int(cur.lastrowid)
    bus.emit(None, "auto_post", "publish_queued", data={"draft_id": draft_id, "publish_job": job_id})
    return job_id


def queue_due_approved(limit: int = 20) -> list[int]:
    """Ensure approved drafts have publish jobs."""
    init()
    with db.conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM drafts WHERE status='approved' ORDER BY scheduled_for, id LIMIT ?",
            (limit,),
        ).fetchall()]
    return [queue_draft(int(row["id"])) for row in rows]


def status() -> dict:
    init()
    with db.conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT status, COUNT(*) AS n FROM publish_jobs GROUP BY status"
        ).fetchall()]
        recent = [dict(r) for r in c.execute(
            "SELECT id,draft_id,provider,status,scheduled_for,attempts,updated_at "
            "FROM publish_jobs ORDER BY updated_at DESC LIMIT 20"
        ).fetchall()]
    return {
        "mode": config.AUTOPOST_MODE,
        "dry_run": config.AUTOPOST_DRY_RUN,
        "webhook_configured": bool(config.AUTOPOST_WEBHOOK_URL),
        "counts": {r["status"]: r["n"] for r in rows},
        "recent": recent,
    }


def run_once(limit: int = 5) -> dict:
    """Publish queued jobs that are due now."""
    init()
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
    with db.conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM publish_jobs WHERE status='queued' "
            "AND (scheduled_for IS NULL OR scheduled_for='' OR scheduled_for<=?) "
            "ORDER BY scheduled_for, id LIMIT ?",
            (now_iso, limit),
        ).fetchall()]

    results = []
    for row in rows:
        results.append(_run_job(row))
    return {"processed": len(results), "results": results, "status": status()}


def _run_job(row: dict) -> dict:
    job_id = int(row["id"])
    payload = json.loads(row.get("payload") or "{}")
    _mark(job_id, "running")
    try:
        if config.AUTOPOST_DRY_RUN or row["provider"] == "local_manifest":
            response = _write_manifest(payload)
        elif row["provider"] == "webhook":
            response = _post_webhook(payload)
        else:
            raise RuntimeError(f"unsupported AUTOPOST_MODE={row['provider']}")
        _mark(job_id, "published", response=response)
        db.update_draft(int(row["draft_id"]), status="published")
        bus.emit(None, "auto_post", "published", data={"draft_id": row["draft_id"], "response": response})
        return {"job_id": job_id, "ok": True, "response": response}
    except Exception as exc:
        _mark(job_id, "failed", response=repr(exc))
        bus.emit(None, "auto_post", "publish_failed", repr(exc), data={"draft_id": row["draft_id"]})
        return {"job_id": job_id, "ok": False, "error": repr(exc)}


def _mark(job_id: int, status_: str, response: str | dict | None = None) -> None:
    resp = json.dumps(response) if isinstance(response, (dict, list)) else response
    with db.conn() as c:
        c.execute(
            "UPDATE publish_jobs SET status=?, response=COALESCE(?,response), "
            "attempts=attempts+1, updated_at=? WHERE id=?",
            (status_, resp, time.time(), job_id),
        )


def _payload_for(draft: dict) -> dict:
    return {
        "draft_id": draft["id"],
        "pipeline": draft.get("pipeline"),
        "topic": draft.get("topic"),
        "title": draft.get("title"),
        "script": draft.get("script"),
        "video_path": draft.get("video_path"),
        "thumb_path": draft.get("thumb_path"),
        "scheduled_for": draft.get("scheduled_for"),
    }


def _write_manifest(payload: dict) -> dict:
    config.LOGS.mkdir(parents=True, exist_ok=True)
    out = config.LOGS / "autopost-manifest.jsonl"
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), **payload}) + "\n")
    return {"provider": "local_manifest", "path": str(out)}


def _post_webhook(payload: dict) -> dict:
    if not config.AUTOPOST_WEBHOOK_URL:
        raise RuntimeError("AUTOPOST_WEBHOOK_URL is not configured")
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        config.AUTOPOST_WEBHOOK_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=20) as res:
        text = res.read().decode("utf-8", errors="replace")
        return {"provider": "webhook", "status": res.status, "body": text[:1000]}
