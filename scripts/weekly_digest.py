"""Once-a-week LLM synthesis. Feed last 7 days of data + notes/ to the model,
ask for 3 directions worth deep-diving + WHY they matter for a SaaS founder
looking at AI-agent-era opportunities."""
from __future__ import annotations
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import db as dbmod  # noqa: E402
from paigod import chat  # noqa: E402

ROOT = SCRIPT_DIR.parent
WEEKLY_DIR = ROOT / "reports" / "weekly"
NOTES_DIR = ROOT / "notes"

SYSTEM = """You are an analyst helping a SaaS founder evaluate AI-agent-era startup opportunities.
You have one week of GitHub Trending, Hacker News (AI-flavored), and Product Hunt AI data,
plus the founder's own free-form notes. Your output goes into a private markdown digest.

Write the digest in Chinese (zh-CN), pragmatic and decisive. Format:

# 本周雷达 — YYYY-WW

## 一句话总览
（≤30 字，本周最重要的 signal）

## 三个值得深挖的方向
For each, write a short ## section:
1. **方向名**（一句子标题）
2. 数据支撑（具体 repo / HN 帖 / PH 产品，标 [slug] 引用，不要堆砌，2-4 个最有说服力的）
3. 为什么这是机会（说清"缝隙"在哪：什么用户痛点 / 什么现成方案不够好 / 什么时机刚好）
4. 与他的 SaaS 背景的契合点（哪里可以借力，哪里需要新能力）
5. 立即可做的小动作（1-2 个用户访谈、原型、调研动作）

## 反直觉的 1 个观察
（数据里某个看着不显眼但实际重要的反常信号）

## 跟他笔记的呼应
（如果 notes 里提过相关想法，明确点出来；没相关就说 "本周笔记无相关线索"）

避免：罗列项目（堆数据）、笼统空话（"AI 改变世界"）、不带数据支撑的判断。
重点：找"为什么是现在"和"为什么是这个人"的契合。"""


def collect_week(conn: sqlite3.Connection, days: int = 7) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT i.source, i.source_id, i.title, i.url, i.description, i.language,
               i.repo_created_at, i.first_seen_at, t.bucket, t.audience, t.free_tags,
               t.rationale
        FROM items i LEFT JOIN tags t ON t.item_id = i.id
        WHERE i.last_seen_at >= ?
        ORDER BY i.first_seen_at DESC
    """, (cutoff,)).fetchall()
    items = []
    for r in rows:
        try:
            tags = json.loads(r["free_tags"]) if r["free_tags"] else []
        except json.JSONDecodeError:
            tags = []
        latest = conn.execute(
            "SELECT metric, value FROM metrics WHERE item_id=(SELECT id FROM items WHERE source=? AND source_id=?) ORDER BY snapshot_at DESC LIMIT 1",
            (r["source"], r["source_id"]),
        ).fetchone()
        items.append({
            "source": r["source"], "id": r["source_id"], "title": r["title"],
            "url": r["url"], "lang": r["language"], "desc": (r["description"] or "")[:200],
            "bucket": r["bucket"], "audience": r["audience"], "tags": tags,
            "rationale": r["rationale"] or "", "created": r["repo_created_at"],
            "metric": dict(latest) if latest else None,
        })
    return {"items": items, "from": cutoff}


def load_notes(days: int = 30) -> str:
    if not NOTES_DIR.exists():
        return ""
    blobs = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for p in sorted(NOTES_DIR.glob("*.md")):
        mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            continue
        blobs.append(f"### {p.name}\n{p.read_text(encoding='utf-8')[:2000]}")
    return "\n\n".join(blobs)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="pa/gpt-5.5")
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()

    conn = dbmod.connect()
    data = collect_week(conn, days=args.days)
    conn.close()
    notes = load_notes(days=30)

    iso_week = datetime.now(timezone.utc).strftime("%Y-W%V")
    payload = {
        "window_days": args.days,
        "item_count": len(data["items"]),
        "items": data["items"],
        "owner_notes": notes,
    }
    user_msg = (
        f"本周数据 (week {iso_week}, {len(data['items'])} items):\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)[:60000]}\n```\n\n"
        "按 system 要求输出 markdown digest。"
    )
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_msg},
    ]
    md = chat(messages, model=args.model, max_tokens=4000)

    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    out = WEEKLY_DIR / f"{iso_week}.md"
    out.write_text(md, encoding="utf-8")
    print(f"wrote {out}  ({len(data['items'])} items, {len(notes)} chars of notes)")


if __name__ == "__main__":
    main()
