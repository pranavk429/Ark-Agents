"""SQLite storage. One connection per operation — safe across threads."""
import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "tower.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, task TEXT, pack TEXT, mode TEXT,
  status TEXT, context_trust TEXT, created_at REAL
);
-- One append-only stream. kind='decision' rows are the formal audit record;
-- the run screen renders every kind in order.
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT, step INTEGER, kind TEXT,
  tool TEXT, decision TEXT, data TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT, step INTEGER, tool TEXT, args_preview TEXT,
  risk TEXT, status TEXT, created_at REAL, decided_at REAL
);
CREATE TABLE IF NOT EXISTS scoreboard (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id TEXT, family TEXT, is_attack INTEGER, governed INTEGER,
  attack_landed INTEGER, task_completed INTEGER, created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id, id);
"""


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init():
    with connect() as c:
        c.executescript(SCHEMA)


def table_names():
    with connect() as c:
        rows = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    return [r["name"] for r in rows]


def new_job(job_id, task, pack, mode):
    # OR REPLACE so a re-run of a fixed job id starts genuinely fresh. The
    # scoreboard sweep names its jobs after the case, so an interrupted sweep
    # leaves a jobs row with no result row; without this the resume the sweep
    # promises dies on a UNIQUE constraint at the first unfinished case.
    # Agent runs use a random uuid, so this never collides for them.
    with connect() as c:
        c.execute(
            "INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?,?,?)",
            (job_id, task, pack, mode, "running", "trusted", time.time()),
        )


def set_job(job_id, **fields):
    keys = ", ".join(f"{k}=?" for k in fields)
    with connect() as c:
        c.execute(f"UPDATE jobs SET {keys} WHERE id=?", (*fields.values(), job_id))


def get_job(job_id):
    with connect() as c:
        return c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def append_event(job_id, step, kind, data, tool=None, decision=None):
    with connect() as c:
        c.execute(
            "INSERT INTO events (job_id,step,kind,tool,decision,data,created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (job_id, step, kind, tool, decision, json.dumps(data), time.time()),
        )


def events_for(job_id):
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM events WHERE job_id=? ORDER BY id", (job_id,)
        ).fetchall()
    return [{**dict(r), "data": json.loads(r["data"])} for r in rows]


def all_decisions(limit=200):
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM events WHERE kind='decision' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{**dict(r), "data": json.loads(r["data"])} for r in rows]
