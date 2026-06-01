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
