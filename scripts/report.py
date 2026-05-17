"""Generate reports/YYYY-MM-DD.md grouped by bucket and audience, sorted by 7-day star delta."""
from __future__ import annotations
import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import db as dbmod  # noqa: E402

ROOT = SCRIPT_DIR.parent
REPORTS_DIR = ROOT / "reports"

BUCKETS_ORDER = ["ai-agent", "ai-app", "ai-infra", "devtool", "data", "security", "web-framework", "other"]


def _delta(conn: sqlite3.Connection, item_id: int, metric: str, days: int) -> int | None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cur = conn.execute(
        "SELECT value FROM metrics WHERE item_id=? AND metric=? ORDER BY snapshot_at ASC LIMIT 1",
        (item_id, metric),
    )
    first = cur.fetchone()
    cur = conn.execute(
        "SELECT value FROM metrics WHERE item_id=? AND metric=? AND snapshot_at <= ? ORDER BY snapshot_at DESC LIMIT 1",
        (item_id, metric, cutoff),
    )
    before = cur.fetchone()
    cur = conn.execute(
        "SELECT value FROM metrics WHERE item_id=? AND metric=? ORDER BY snapshot_at DESC LIMIT 1",
        (item_id, metric),
    )
    latest = cur.fetchone()
    if not latest:
        return None
    baseline = before or first
    if not baseline:
        return None
    return int(latest["value"] - baseline["value"])


def gather(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("""
        SELECT items.id, items.source, items.source_id, items.title, items.url, items.owner,
               items.language, items.description, items.repo_created_at, items.topics_json,
               tags.bucket, tags.audience, tags.free_tags, tags.rationale
        FROM items
        LEFT JOIN tags ON tags.item_id = items.id
        WHERE items.source = 'github_trending'
    """).fetchall()
    out: list[dict] = []
    for r in rows:
        latest = conn.execute(
            "SELECT value, snapshot_at FROM metrics WHERE item_id=? AND metric='stars' ORDER BY snapshot_at DESC LIMIT 1",
            (r["id"],),
        ).fetchone()
        stars = int(latest["value"]) if latest else 0
        delta_7d = _delta(conn, r["id"], "stars", 7)
        delta_1d = _delta(conn, r["id"], "stars", 1)
        windows = conn.execute(
            "SELECT DISTINCT window FROM trending_appearances WHERE item_id=? AND seen_at >= ?",
            (r["id"], (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()),
        ).fetchall()
        windows = sorted({w["window"] for w in windows})
        try:
            created_dt = datetime.fromisoformat((r["repo_created_at"] or "").replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - created_dt).days
        except Exception:
            age_days = None
        try:
            free_tags = json.loads(r["free_tags"]) if r["free_tags"] else []
        except json.JSONDecodeError:
            free_tags = []
        try:
            topics = json.loads(r["topics_json"]) if r["topics_json"] else []
        except json.JSONDecodeError:
            topics = []
        out.append({
            "id": r["id"],
            "slug": r["source_id"],
            "url": r["url"],
            "description": r["description"] or "",
            "language": r["language"] or "",
            "stars": stars,
            "delta_1d": delta_1d,
            "delta_7d": delta_7d,
            "age_days": age_days,
            "windows": windows,
            "bucket": r["bucket"] or "other",
            "audience": r["audience"] or "?",
            "free_tags": free_tags,
            "rationale": r["rationale"] or "",
            "topics": topics,
        })
    return out


def format_repo_line(r: dict, superstar_threshold: int) -> str:
    flag = " 🚀" if (r["delta_1d"] or 0) >= superstar_threshold else ""
    tags = ", ".join(r["free_tags"]) if r["free_tags"] else ""
    age = f"{r['age_days']}d" if r["age_days"] is not None else "?"
    delta7 = f"+{r['delta_7d']}" if r["delta_7d"] is not None else "·"
    delta1 = f"+{r['delta_1d']}/d" if r["delta_1d"] is not None else "·"
    aud = f"[{r['audience']}]"
    return (
        f"- **[{r['slug']}]({r['url']})**{flag} · ★{r['stars']:,} ({delta1}, 7d {delta7}) · "
        f"{r['language'] or '—'} · age {age} · {aud}\n"
        f"  - {r['description']}\n"
        + (f"  - tags: _{tags}_\n" if tags else "")
        + (f"  - 💡 {r['rationale']}\n" if r["rationale"] else "")
    )


def build_markdown(items: list[dict], *, superstar_threshold: int = 500) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_bucket[it["bucket"]].append(it)
    for v in by_bucket.values():
        v.sort(key=lambda x: (x["delta_7d"] or 0, x["delta_1d"] or 0, x["stars"]), reverse=True)

    lines: list[str] = []
    lines.append(f"# GitHub Trending Radar — {today}\n")
    lines.append(f"_{len(items)} repos under 180 days, ≥100 stars, seen on official trending_\n")

    superstars = [i for i in items if (i["delta_1d"] or 0) >= superstar_threshold]
    if superstars:
        lines.append("## 🚀 Superstars (1d Δ ≥ %d)\n" % superstar_threshold)
        for s in sorted(superstars, key=lambda x: x["delta_1d"] or 0, reverse=True):
            lines.append(format_repo_line(s, superstar_threshold))

    audience_summary: dict[str, int] = defaultdict(int)
    for it in items:
        audience_summary[it["audience"]] += 1
    if audience_summary:
        parts = " · ".join(f"{k}: {v}" for k, v in sorted(audience_summary.items()))
        lines.append(f"## Audience mix\n_{parts}_\n")

    for bucket in BUCKETS_ORDER:
        if bucket not in by_bucket:
            continue
        bucket_items = by_bucket[bucket]
        lines.append(f"## {bucket} ({len(bucket_items)})\n")
        for r in bucket_items:
            lines.append(format_repo_line(r, superstar_threshold))

    lines.append("---\n")
    lines.append(f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}_  \n")
    lines.append("_Source: github.com/trending (daily/weekly/monthly) + GitHub API + paigod pa/gpt-5.5_\n")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--superstar", type=int, default=500)
    args = ap.parse_args()

    conn = dbmod.connect()
    items = gather(conn)
    conn.close()
    md = build_markdown(items, superstar_threshold=args.superstar)

    REPORTS_DIR.mkdir(exist_ok=True)
    out = args.out or REPORTS_DIR / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.md"
    out.write_text(md, encoding="utf-8")
    print(f"wrote {out}  ({len(items)} items)")


if __name__ == "__main__":
    main()
