"""SQLite state: drafts, scheduling, voice-rotation cursor, asset license log."""
from __future__ import annotations
import sqlite3, json, time
from pathlib import Path
from contextlib import contextmanager
from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline      TEXT NOT NULL,            -- 'A' or 'B'
    topic         TEXT NOT NULL,
    category      TEXT,
    title         TEXT,
    script        TEXT,
    video_path    TEXT,
    thumb_path    TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|rejected|published|failed
    discord_msg   INTEGER,
    week          TEXT,                     -- ISO year-week, e.g. 2026-W23
    scheduled_for TEXT,                     -- ISO datetime of publish slot
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
    k TEXT PRIMARY KEY,
    v TEXT
);
CREATE TABLE IF NOT EXISTS assets (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id  INTEGER,
    kind      TEXT,        -- footage|image|music
    source    TEXT,        -- archive.org|pixabay|pexels|local
    url       TEXT,
    license   TEXT,
    local_path TEXT,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS trend_candidates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT,                         -- reddit|youtube_rss|google_trends
    topic       TEXT NOT NULL,
    raw_score   REAL DEFAULT 0.0,             -- source-provided signal
    prior_score REAL DEFAULT 0.0,             -- from supervisor.priors
    used        INTEGER DEFAULT 0,            -- 1 once dispatched to production
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS engagement_metrics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id    INTEGER,
    platform    TEXT,                         -- youtube|tiktok
    video_id    TEXT,                         -- platform's own ID
    views       INTEGER DEFAULT 0,
    likes       INTEGER DEFAULT 0,
    comments    INTEGER DEFAULT 0,
    shares      INTEGER DEFAULT 0,
    ctr         REAL DEFAULT 0.0,
    reward      REAL DEFAULT 0.0,             -- computed by engagement module
    fetched_at  REAL
);
CREATE TABLE IF NOT EXISTS platform_tokens (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    platform     TEXT UNIQUE,                 -- youtube|tiktok
    access_token TEXT,
    refresh_token TEXT,
    expires_at   REAL,
    scope        TEXT,
    updated_at   REAL
);
CREATE TABLE IF NOT EXISTS code_patches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path   TEXT NOT NULL,
    error_summary TEXT,
    patch_diff  TEXT,                         -- unified diff string
    applied     INTEGER DEFAULT 0,
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS niche_research (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    niche        TEXT NOT NULL,               -- chosen niche/category
    criteria_json TEXT,                       -- transparent scoring breakdown + ranked candidates
    score        REAL DEFAULT 0.0,            -- winning niche score
    created_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS fact_checks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id     INTEGER,
    claim        TEXT NOT NULL,
    verdict      TEXT,                        -- supported|uncertain|contradicted
    rationale    TEXT,
    created_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    target       TEXT NOT NULL,               -- which agent/stage was reviewed
    draft_id     INTEGER,
    verdict      TEXT,                        -- pass|flag|redo
    detail       TEXT,
    resolved     INTEGER DEFAULT 0,           -- 1 once acted on / dismissed
    created_at   REAL NOT NULL
);
"""

@contextmanager
def conn():
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()

def init():
    with conn() as c:
        c.executescript(SCHEMA)

def add_draft(pipeline, topic, category, title, script) -> int:
    now = time.time()
    with conn() as c:
        cur = c.execute(
            "INSERT INTO drafts(pipeline,topic,category,title,script,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (pipeline, topic, category, title, script, now, now),
        )
        return cur.lastrowid

def update_draft(draft_id, **fields):
    if not fields:
        return
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k}=?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE drafts SET {cols} WHERE id=?", (*fields.values(), draft_id))

def get_draft(draft_id):
    with conn() as c:
        r = c.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
        return dict(r) if r else None

def get_draft_by_msg(discord_msg):
    with conn() as c:
        r = c.execute("SELECT * FROM drafts WHERE discord_msg=?", (discord_msg,)).fetchone()
        return dict(r) if r else None

def drafts_by_status(pipeline, status, week=None):
    q = "SELECT * FROM drafts WHERE pipeline=? AND status=?"
    args = [pipeline, status]
    if week:
        q += " AND week=?"; args.append(week)
    with conn() as c:
        return [dict(r) for r in c.execute(q, args).fetchall()]

def count_status(pipeline, status, week):
    with conn() as c:
        return c.execute(
            "SELECT COUNT(*) FROM drafts WHERE pipeline=? AND status=? AND week=?",
            (pipeline, status, week),
        ).fetchone()[0]

# ---- voice rotation cursor ----
def next_voice_index(pool_len: int) -> int:
    with conn() as c:
        row = c.execute("SELECT v FROM kv WHERE k='voice_cursor'").fetchone()
        idx = int(row["v"]) if row else 0
        nxt = (idx + 1) % pool_len
        c.execute("INSERT INTO kv(k,v) VALUES('voice_cursor',?) "
                  "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (str(nxt),))
        return idx

def log_asset(draft_id, kind, source, url, license, local_path):
    with conn() as c:
        c.execute(
            "INSERT INTO assets(draft_id,kind,source,url,license,local_path,created_at) VALUES(?,?,?,?,?,?,?)",
            (draft_id, kind, source, url, license, str(local_path), time.time()),
        )

# ---- trend candidates ----
def add_trend(source, topic, raw_score, prior_score) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO trend_candidates(source,topic,raw_score,prior_score,created_at) VALUES(?,?,?,?,?)",
            (source, topic, raw_score, prior_score, time.time()),
        )
        return cur.lastrowid

def top_trends(n=5, unused_only=True) -> list:
    q = "SELECT * FROM trend_candidates"
    if unused_only:
        q += " WHERE used=0"
    q += " ORDER BY created_at DESC LIMIT ?"
    with conn() as c:
        return [dict(r) for r in c.execute(q, (n,)).fetchall()]

def mark_trend_used(trend_id: int) -> None:
    with conn() as c:
        c.execute("UPDATE trend_candidates SET used=1 WHERE id=?", (trend_id,))

# ---- engagement metrics ----
def log_engagement(draft_id, platform, video_id, views, likes, comments, shares, ctr, reward) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO engagement_metrics(draft_id,platform,video_id,views,likes,comments,shares,ctr,reward,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (draft_id, platform, video_id, views, likes, comments, shares, ctr, reward, time.time()),
        )
        return cur.lastrowid

def get_engagement_for_draft(draft_id, platform=None) -> list:
    q = "SELECT * FROM engagement_metrics WHERE draft_id=?"
    args = [draft_id]
    if platform:
        q += " AND platform=?"; args.append(platform)
    q += " ORDER BY fetched_at DESC"
    with conn() as c:
        return [dict(r) for r in c.execute(q, args).fetchall()]

def recent_engagement(n=50) -> list:
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM engagement_metrics ORDER BY fetched_at DESC LIMIT ?", (n,)
        ).fetchall()]

# ---- platform tokens ----
def get_platform_token(platform) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM platform_tokens WHERE platform=?", (platform,)).fetchone()
        return dict(r) if r else None

def set_platform_token(platform, access_token, refresh_token, expires_at, scope) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO platform_tokens(platform,access_token,refresh_token,expires_at,scope,updated_at) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(platform) DO UPDATE SET access_token=excluded.access_token, refresh_token=excluded.refresh_token, expires_at=excluded.expires_at, scope=excluded.scope, updated_at=excluded.updated_at",
            (platform, access_token, refresh_token, expires_at, scope, time.time()),
        )

# ---- code patches ----
def add_patch(file_path, error_summary, patch_diff) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO code_patches(file_path,error_summary,patch_diff,created_at) VALUES(?,?,?,?)",
            (file_path, error_summary, patch_diff, time.time()),
        )
        return cur.lastrowid

def get_patches(n=50, applied_only=False) -> list:
    q = "SELECT * FROM code_patches"
    if applied_only:
        q += " WHERE applied=1"
    q += " ORDER BY created_at DESC LIMIT ?"
    with conn() as c:
        return [dict(r) for r in c.execute(q, (n,)).fetchall()]

def apply_patch(patch_id: int) -> None:
    with conn() as c:
        c.execute("UPDATE code_patches SET applied=1 WHERE id=?", (patch_id,))

# ---- niche research ----
def add_niche(niche, criteria, score) -> int:
    payload = criteria if isinstance(criteria, str) else json.dumps(criteria)
    with conn() as c:
        cur = c.execute(
            "INSERT INTO niche_research(niche,criteria_json,score,created_at) VALUES(?,?,?,?)",
            (niche, payload, score, time.time()),
        )
        return cur.lastrowid

def recent_niche(n=20) -> list:
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM niche_research ORDER BY created_at DESC LIMIT ?", (n,)
        ).fetchall()]

# ---- fact checks ----
def add_fact_check(draft_id, claim, verdict, rationale) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO fact_checks(draft_id,claim,verdict,rationale,created_at) VALUES(?,?,?,?,?)",
            (draft_id, claim, verdict, rationale, time.time()),
        )
        return cur.lastrowid

def fact_checks_for_draft(draft_id) -> list:
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM fact_checks WHERE draft_id=? ORDER BY id", (draft_id,)
        ).fetchall()]

def recent_fact_checks(n=50) -> list:
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM fact_checks ORDER BY created_at DESC LIMIT ?", (n,)
        ).fetchall()]

# ---- reviews ----
def add_review(target, draft_id, verdict, detail) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO reviews(target,draft_id,verdict,detail,created_at) VALUES(?,?,?,?,?)",
            (target, draft_id, verdict, detail, time.time()),
        )
        return cur.lastrowid

def recent_reviews(n=50) -> list:
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM reviews ORDER BY created_at DESC LIMIT ?", (n,)
        ).fetchall()]

def resolve_review(review_id: int) -> None:
    with conn() as c:
        c.execute("UPDATE reviews SET resolved=1 WHERE id=?", (review_id,))
