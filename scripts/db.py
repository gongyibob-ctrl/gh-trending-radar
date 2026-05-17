"""SQLite layer. Schema is intentionally generic so HN/YC/Product Hunt
share the same tables as GitHub trending — only `source` differs."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).resolve().parent.parent / "db.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    title           TEXT NOT NULL,
    url             TEXT NOT NULL,
    owner           TEXT,
    owner_type      TEXT,
    language        TEXT,
    description     TEXT,
    license         TEXT,
    topics_json     TEXT,
    readme_excerpt  TEXT,
    repo_created_at TEXT,
    first_seen_at   TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL,
    raw_json        TEXT,
    UNIQUE(source, source_id)
);

CREATE TABLE IF NOT EXISTS metrics (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id      INTEGER NOT NULL REFERENCES items(id),
    metric       TEXT NOT NULL,
    value        REAL NOT NULL,
    snapshot_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_item_time ON metrics(item_id, metric, snapshot_at);

CREATE TABLE IF NOT EXISTS trending_appearances (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id       INTEGER NOT NULL REFERENCES items(id),
    window        TEXT NOT NULL,
    rank          INTEGER,
    stars_today   INTEGER,
    seen_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     INTEGER NOT NULL REFERENCES items(id),
    bucket      TEXT,
    audience    TEXT,
    free_tags   TEXT,
    rationale   TEXT,
    model       TEXT,
    tagged_at   TEXT NOT NULL,
    UNIQUE(item_id, model)
);

CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     INTEGER REFERENCES items(id),
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_item(conn: sqlite3.Connection, *, source: str, source_id: str, title: str,
                url: str, **fields) -> int:
    now = now_iso()
    cur = conn.execute(
        "SELECT id FROM items WHERE source=? AND source_id=?",
        (source, source_id),
    )
    row = cur.fetchone()
    raw_json = json.dumps(fields.pop("raw", None), ensure_ascii=False) if fields.get("raw") is not None else None
    topics = fields.pop("topics", None)
    topics_json = json.dumps(topics, ensure_ascii=False) if topics is not None else None
    payload = dict(
        owner=fields.get("owner"),
        owner_type=fields.get("owner_type"),
        language=fields.get("language"),
        description=fields.get("description"),
        license=fields.get("license"),
        topics_json=topics_json,
        readme_excerpt=fields.get("readme_excerpt"),
        repo_created_at=fields.get("repo_created_at"),
        raw_json=raw_json,
    )
    if row:
        item_id = row["id"]
        conn.execute(
            """UPDATE items SET title=?, url=?, owner=COALESCE(?,owner),
               owner_type=COALESCE(?,owner_type), language=COALESCE(?,language),
               description=COALESCE(?,description), license=COALESCE(?,license),
               topics_json=COALESCE(?,topics_json), readme_excerpt=COALESCE(?,readme_excerpt),
               repo_created_at=COALESCE(?,repo_created_at), raw_json=COALESCE(?,raw_json),
               last_seen_at=?
               WHERE id=?""",
            (title, url, payload["owner"], payload["owner_type"], payload["language"],
             payload["description"], payload["license"], payload["topics_json"],
             payload["readme_excerpt"], payload["repo_created_at"], payload["raw_json"],
             now, item_id),
        )
    else:
        cur = conn.execute(
            """INSERT INTO items (source, source_id, title, url, owner, owner_type,
               language, description, license, topics_json, readme_excerpt,
               repo_created_at, first_seen_at, last_seen_at, raw_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (source, source_id, title, url, payload["owner"], payload["owner_type"],
             payload["language"], payload["description"], payload["license"],
             payload["topics_json"], payload["readme_excerpt"],
             payload["repo_created_at"], now, now, payload["raw_json"]),
        )
        item_id = cur.lastrowid
    return item_id


def add_metric(conn, item_id: int, metric: str, value: float, snapshot_at: str | None = None) -> None:
    conn.execute(
        "INSERT INTO metrics (item_id, metric, value, snapshot_at) VALUES (?,?,?,?)",
        (item_id, metric, value, snapshot_at or now_iso()),
    )


def add_trending_appearance(conn, item_id: int, window: str, rank: int | None,
                             stars_today: int | None) -> None:
    conn.execute(
        "INSERT INTO trending_appearances (item_id, window, rank, stars_today, seen_at) VALUES (?,?,?,?,?)",
        (item_id, window, rank, stars_today, now_iso()),
    )


def set_tag(conn, item_id: int, *, bucket: str, audience: str | None, free_tags: list[str],
            rationale: str | None, model: str) -> None:
    conn.execute(
        """INSERT INTO tags (item_id, bucket, audience, free_tags, rationale, model, tagged_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(item_id, model) DO UPDATE SET
               bucket=excluded.bucket,
               audience=excluded.audience,
               free_tags=excluded.free_tags,
               rationale=excluded.rationale,
               tagged_at=excluded.tagged_at""",
        (item_id, bucket, audience, json.dumps(free_tags, ensure_ascii=False),
         rationale, model, now_iso()),
    )


def needs_tagging(conn, item_id: int, model: str) -> bool:
    cur = conn.execute("SELECT 1 FROM tags WHERE item_id=? AND model=?", (item_id, model))
    return cur.fetchone() is None
