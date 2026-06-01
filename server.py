#!/usr/bin/env python
"""Lightweight backend API for the dashboard (stdlib only, threaded).

Exposes the bus/db to the web UI and drives renders. No external web framework
so it runs on any PC. Render jobs run on a background thread; the UI polls
/api/render/<job>/events for live progress.

Run:  py server.py            -> http://127.0.0.1:8787
Then open dashboard/index.html (it auto-detects the API; falls back to mock).
"""
from __future__ import annotations
import datetime as dt
import json, threading, logging, mimetypes, shutil
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse, unquote

from pipelines.common import autopost, bus, config, db, hunyuan_video, supervisor
from pipelines import agents, batch, pipeline_a

log = logging.getLogger("server")
ROOT = Path(__file__).resolve().parent
DASH = ROOT / "dashboard"
RUNNER = agents.get_runner()
PUBLISH_HOUR = 9


def _next_slot(week: str | None, taken: int) -> str:
    """Return the next publish slot ISO timestamp for web approvals."""
    week = week or batch.iso_week()
    monday = dt.datetime.strptime(week + "-1", "%Y-W%W-%w")
    slot = monday.replace(hour=PUBLISH_HOUR, minute=0) + dt.timedelta(
        days=taken % 7,
        hours=taken // 7,
    )
    return slot.isoformat()


def _media_url(path: str | None) -> str:
    if not path:
        return ""
    p = Path(path)
    try:
        rel = p.resolve().relative_to(ROOT)
        return "/media/" + rel.as_posix()
    except Exception:
        return ""


def _draft_payload(row: dict) -> dict:
    scheduled_for = row.get("scheduled_for") or ""
    return {
        "id": str(row["id"]),
        "pipeline": row.get("pipeline") or "",
        "pl": row.get("pipeline") or "",
        "topic": row.get("topic") or "",
        "category": row.get("category") or "default",
        "cat": row.get("category") or "default",
        "title": row.get("title") or row.get("topic") or f"Draft {row['id']}",
        "script": row.get("script") or "",
        "status": row.get("status") or "pending",
        "scheduled_for": scheduled_for,
        "slot": scheduled_for,
        "video_path": row.get("video_path") or "",
        "thumb_path": row.get("thumb_path") or "",
        "video_url": _media_url(row.get("video_path")),
        "thumb_url": _media_url(row.get("thumb_path")),
        "voice": "rotating Kokoro",
    }


def _render_job(topic: str, visual_source: str) -> str:
    """Kick a Pipeline A render on a background thread; return its job id."""
    job_id = bus.new_job("reel_A", {"topic": topic, "visual_source": visual_source})

    def _run():
        try:
            # reuse the same job id so all events land under the polled job
            res = pipeline_a.produce(topic, visual_source=visual_source, job_id=job_id)
            bus.emit(job_id, "server", "render_done",
                     data={"video": res.get("video"), "draft_id": res.get("draft_id"),
                           "target_dur": 0})
            bus.set_status(job_id, "done", result=res)
        except Exception as e:
            bus.set_status(job_id, "failed", error=repr(e))
            bus.emit(job_id, "server", "stage_error", repr(e))

    threading.Thread(target=_run, daemon=True).start()
    return job_id


def _regenerate_job(draft_id: int) -> str:
    rejected = db.get_draft(draft_id)
    if not rejected:
        raise ValueError(f"draft {draft_id} not found")

    job_id = bus.new_job("reject_regen", {
        "draft_id": draft_id,
        "pipeline": rejected["pipeline"],
        "topic": rejected["topic"],
    })

    def _run():
        try:
            bus.set_status(job_id, "running")
            res = batch.regenerate_one(
                rejected["pipeline"],
                rejected["topic"],
                rejected.get("week"),
            )
            bus.emit(job_id, "server", "replacement_ready", data=res)
            bus.set_status(job_id, "done", result=res)
        except Exception as e:
            bus.set_status(job_id, "failed", error=repr(e))
            bus.emit(job_id, "server", "stage_error", repr(e))

    threading.Thread(target=_run, daemon=True).start()
    return job_id


class Handler(BaseHTTPRequestHandler):
    server_version = "ReelPipeline/1.0"

    def _send(self, code: int, body: bytes, ctype="application/json", *, head_only: bool = False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", config.CORS_ORIGIN)
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode())

    def do_OPTIONS(self):
        self._send(204, b"")

    def do_HEAD(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path in ("/", "/index.html"):
                return self._file(DASH / "index.html", head_only=True)
            if path.startswith("/dashboard/"):
                return self._file(ROOT / path.lstrip("/"), head_only=True)
            if path.startswith("/media/"):
                return self._media_file(path, head_only=True)
            if path.startswith("/api/"):
                # Health checks and proxies commonly issue HEAD before GET.
                return self._send(200, b"", "application/json", head_only=True)
            return self._send(404, b"", "application/json", head_only=True)
        except Exception as e:
            log.exception("HEAD %s", path)
            body = json.dumps({"error": repr(e)}).encode()
            self._send(500, body, "application/json", head_only=True)

    def log_message(self, *a):  # quiet
        pass

    def _authorized(self) -> bool:
        expected = config.REEL_API_KEY
        return not expected or self.headers.get("X-API-Key", "") == expected

    # ----------------------------------------------------------- GET
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path in ("/", "/index.html"):
                return self._file(DASH / "index.html")
            if path.startswith("/api/"):
                return self._api_get(path, query)
            if path.startswith("/dashboard/"):
                return self._file(ROOT / path.lstrip("/"))
            if path.startswith("/media/"):
                return self._media_file(path)
            return self._json({"error": "not found"}, 404)
        except Exception as e:
            log.exception("GET %s", path)
            self._json({"error": repr(e)}, 500)

    def _file(self, p: Path, *, head_only: bool = False):
        if not p.exists():
            return self._json({"error": "not found"}, 404)
        ctype = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        self._send(200, p.read_bytes(), ctype, head_only=head_only)

    def _media_file(self, path: str, *, head_only: bool = False):
        rel = unquote(path.removeprefix("/media/"))
        p = (ROOT / rel).resolve()
        try:
            p.relative_to(ROOT.resolve())
        except ValueError:
            return self._json({"error": "not found"}, 404)
        return self._file(p, head_only=head_only)

    def _send_cors_headers(self):
        """Add CORS headers to allow external access."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def _api_get(self, path: str, query: dict[str, list[str]]):
        if path == "/api/health":
            ffmpeg_ok = bool(shutil.which(config.FFMPEG) or Path(config.FFMPEG).exists())
            return self._json({"ok": True, "hunyuan": hunyuan_video.is_available(),
                               "engine": hunyuan_video.ENGINE_NAME,
                               "ffmpeg": ffmpeg_ok,
                               "hunyuan_status": hunyuan_video.health(),
                               "autopost": autopost.status()})
        if path == "/api/agents":
            return self._json(RUNNER.health())
        if path == "/api/drafts":
            pipeline = (query.get("pipeline") or [""])[0]
            status = (query.get("status") or [""])[0]
            week = (query.get("week") or [""])[0]
            where, args = [], []
            if pipeline:
                where.append("pipeline=?"); args.append(pipeline)
            if status:
                where.append("status=?"); args.append(status)
            if week:
                where.append("week=?"); args.append(week)
            clause = (" WHERE " + " AND ".join(where)) if where else ""
            with db.conn() as c:
                rows = [dict(r) for r in c.execute(
                    "SELECT id,pipeline,topic,category,title,status,scheduled_for "
                    ",script,video_path,thumb_path,week FROM drafts"
                    f"{clause} ORDER BY id DESC LIMIT 200", args).fetchall()]
            return self._json([_draft_payload(r) for r in rows])
        if path.startswith("/api/drafts/") and path.endswith("/assets"):
            draft_id = path.split("/")[3]
            with db.conn() as c:
                rows = [dict(r) for r in c.execute(
                    "SELECT kind,source,url,license,local_path,created_at "
                    "FROM assets WHERE draft_id=? ORDER BY id", (draft_id,)
                ).fetchall()]
            return self._json(rows)
        if path == "/api/jobs":
            with db.conn() as c:
                rows = [dict(r) for r in c.execute(
                    "SELECT id,kind,status,attempts,updated_at FROM jobs "
                    "ORDER BY updated_at DESC LIMIT 100").fetchall()]
            return self._json(rows)
        if path == "/api/events":
            return self._json(bus.recent_events(limit=80))
        if path.startswith("/api/render/") and path.endswith("/events"):
            job_id = path.split("/")[3]
            return self._json({"job": bus.get_job(job_id),
                               "events": bus.recent_events(job_id, limit=100)})
        if path == "/api/priors":
            return self._json(supervisor.priors.weights())
        if path == "/api/autopost/status":
            return self._json(autopost.status())
        # AI Team endpoints
        if path == "/api/trends":
            trends = db.top_trends(n=20, unused_only=False)
            return self._json([dict(t) for t in trends])
        if path == "/api/engagement":
            engagement = db.recent_engagement(n=50)
            return self._json([dict(e) for e in engagement])
        if path == "/api/patches":
            patches = db.get_patches(n=50, applied_only=False)
            return self._json([dict(p) for p in patches])
        return self._json({"error": "unknown endpoint"}, 404)

    # ----------------------------------------------------------- POST
    def do_POST(self):
        path = urlparse(self.path).path
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        try:
            if not self._authorized():
                return self._json({"error": "unauthorized"}, 401)
            if path == "/api/render":
                job_id = _render_job(body.get("topic", "Untitled"),
                                     body.get("visual_source", "auto"))
                return self._json({"job_id": job_id})
            if path == "/api/render/cancel":
                bus.cancel(body.get("job_id", "")); return self._json({"ok": True})
            # Handle /api/drafts/{id}/approve
            if path.startswith("/api/drafts/") and path.endswith("/approve"):
                draft_id = int(path.split("/")[3])
                d = db.get_draft(draft_id)
                if not d:
                    return self._json({"error": "draft not found"}, 404)
                week = d.get("week") or batch.iso_week()
                taken = db.count_status(d["pipeline"], "approved", week)
                slot = _next_slot(week, taken)
                db.update_draft(draft_id, status="approved", week=week, scheduled_for=slot)
                bus.emit(None, "ui", "approved", data={"draft_id": draft_id, "slot": slot})
                return self._json({"ok": True, "draft": _draft_payload(db.get_draft(draft_id))})
            # Handle /api/drafts/{id}/reject
            if path.startswith("/api/drafts/") and path.endswith("/reject"):
                draft_id = int(path.split("/")[3])
                d = db.get_draft(draft_id)
                if not d:
                    return self._json({"error": "draft not found"}, 404)
                db.update_draft(draft_id, status="rejected")
                job_id = _regenerate_job(draft_id) if body.get("regenerate", True) else ""
                bus.emit(None, "ui", "rejected", data={"draft_id": draft_id, "job_id": job_id})
                return self._json({"ok": True, "job_id": job_id, "draft": _draft_payload(db.get_draft(draft_id))})
            if path == "/api/approve":
                draft_id = int(body.get("draft_id"))
                d = db.get_draft(draft_id)
                if not d:
                    return self._json({"error": "draft not found"}, 404)
                week = d.get("week") or batch.iso_week()
                taken = db.count_status(d["pipeline"], "approved", week)
                slot = _next_slot(week, taken)
                db.update_draft(draft_id, status="approved", week=week, scheduled_for=slot)
                bus.emit(None, "ui", "approved", data={"draft_id": draft_id, "slot": slot})
                return self._json({"ok": True, "draft": _draft_payload(db.get_draft(draft_id))})
            if path == "/api/reject":
                draft_id = int(body.get("draft_id"))
                d = db.get_draft(draft_id)
                if not d:
                    return self._json({"error": "draft not found"}, 404)
                db.update_draft(draft_id, status="rejected")
                job_id = _regenerate_job(draft_id) if body.get("regenerate", True) else ""
                bus.emit(None, "ui", "rejected", data={"draft_id": draft_id, "job_id": job_id})
                return self._json({"ok": True, "job_id": job_id, "draft": _draft_payload(db.get_draft(draft_id))})
            if path == "/api/variants":
                bus.emit(None, "ui", "make_variants", data={"draft_id": body.get("draft_id")})
                return self._json({"ok": True})
            if path == "/api/episode":
                bus.emit(None, "ui", "new_episode",
                         data={"series": body.get("series", "Series"),
                               "episode": body.get("episode", 1)})
                return self._json({"ok": True})
            if path == "/api/autopost/queue":
                ids = autopost.queue_due_approved(int(body.get("limit", 20)))
                return self._json({"ok": True, "queued": ids, "status": autopost.status()})
            if path == "/api/autopost/run":
                return self._json(autopost.run_once(int(body.get("limit", 5))))
            if path == "/api/settings":
                # Save settings from dashboard
                # In a real app, these would be validated and persisted
                return self._json({"ok": True, "message": "Settings saved"})
            # AI Team endpoints
            if path == "/api/trend_cycle/run":
                bus.emit(None, "ui", "trend_cycle_start")
                return self._json({"ok": True, "message": "Trend cycle triggered"})
            if path.startswith("/api/distribute/"):
                draft_id = int(path.split("/")[3])
                bus.emit(None, "ui", "publish_request", data={"draft_id": draft_id})
                return self._json({"ok": True, "draft_id": draft_id})
            if path.startswith("/api/patches/") and path.endswith("/apply"):
                patch_id = int(path.split("/")[3])
                patch = db.get_patches(n=1, applied_only=False)
                if patch and patch[0]["id"] == patch_id:
                    from pipelines.common import qwen_coder
                    if qwen_coder.apply_patch(patch[0]["patch_diff"], patch[0]["file_path"]):
                        db.apply_patch(patch_id)
                        return self._json({"ok": True, "applied": True})
                return self._json({"error": "patch not found or apply failed"}, 404)
            return self._json({"error": "unknown endpoint"}, 404)
        except Exception as e:
            log.exception("POST %s", path)
            self._json({"error": repr(e)}, 500)


def main(port: int = 8787):
    logging.basicConfig(level=logging.INFO)
    bus.init()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Reel Pipeline API + dashboard on http://127.0.0.1:{port}")
    print(f"Engine: {hunyuan_video.ENGINE_NAME} available={hunyuan_video.is_available()}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
