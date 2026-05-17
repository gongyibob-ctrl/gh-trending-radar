"""Dump SQLite into a static JSON the Next.js dashboard reads at build time."""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import db as dbmod  # noqa: E402

ROOT = SCRIPT_DIR.parent
OUT = ROOT / "dashboard" / "data.json"


def main() -> None:
    conn = dbmod.connect()
    items = []
    rows = conn.execute("""
        SELECT i.id, i.source, i.source_id, i.title, i.url, i.owner, i.language,
               i.description, i.topics_json, i.repo_created_at, i.first_seen_at,
               t.bucket, t.audience, t.free_tags, t.rationale
        FROM items i LEFT JOIN tags t ON t.item_id = i.id
    """).fetchall()
    for r in rows:
        latest_stars = conn.execute(
            "SELECT value FROM metrics WHERE item_id=? AND metric='stars' ORDER BY snapshot_at DESC LIMIT 1",
            (r["id"],),
        ).fetchone()
        latest_hn = conn.execute(
            "SELECT value FROM metrics WHERE item_id=? AND metric='hn_points' ORDER BY snapshot_at DESC LIMIT 1",
            (r["id"],),
        ).fetchone()
        # 7d delta for stars
        first_in_7 = conn.execute(
            "SELECT value FROM metrics WHERE item_id=? AND metric='stars' AND snapshot_at >= ? ORDER BY snapshot_at ASC LIMIT 1",
            (r["id"], (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()),
        ).fetchone()
        delta_7d = None
        if latest_stars and first_in_7:
            delta_7d = int(latest_stars["value"] - first_in_7["value"])
        try:
            tags = json.loads(r["free_tags"]) if r["free_tags"] else []
        except json.JSONDecodeError:
            tags = []
        try:
            topics = json.loads(r["topics_json"]) if r["topics_json"] else []
        except json.JSONDecodeError:
            topics = []
        items.append({
            "id": r["id"],
            "source": r["source"],
            "sourceId": r["source_id"],
            "title": r["title"],
            "url": r["url"],
            "owner": r["owner"],
            "language": r["language"],
            "description": r["description"],
            "createdAt": r["repo_created_at"],
            "firstSeenAt": r["first_seen_at"],
            "bucket": r["bucket"] or "other",
            "audience": r["audience"] or "?",
            "tags": tags,
            "topics": topics,
            "rationale": r["rationale"],
            "stars": int(latest_stars["value"]) if latest_stars else None,
            "stars7dDelta": delta_7d,
            "hnPoints": int(latest_hn["value"]) if latest_hn else None,
        })

    by_bucket: dict[str, int] = {}
    by_audience: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for it in items:
        by_bucket[it["bucket"]] = by_bucket.get(it["bucket"], 0) + 1
        by_audience[it["audience"]] = by_audience.get(it["audience"], 0) + 1
        by_source[it["source"]] = by_source.get(it["source"], 0) + 1

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "items": len(items),
            "byBucket": by_bucket,
            "byAudience": by_audience,
            "bySource": by_source,
        },
        "items": items,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    conn.close()
    print(f"wrote {OUT}  ({len(items)} items)")


if __name__ == "__main__":
    main()
