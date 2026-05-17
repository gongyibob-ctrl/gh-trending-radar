"""Fetch Hacker News front page & best stories, classify AI-flavored ones."""
from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import db as dbmod  # noqa: E402
from classify import classify  # noqa: E402

HN_API = "https://hacker-news.firebaseio.com/v0"
AI_KEYWORDS = {
    "ai", "llm", "gpt", "claude", "agent", "agents", "rag", "embedding",
    "fine-tune", "fine-tuning", "prompt", "mcp", "transformer", "diffusion",
    "openai", "anthropic", "deepseek", "ollama", "langchain", "huggingface",
    "vector", "inference",
}


def _get(path: str) -> dict | list | int | None:
    r = requests.get(f"{HN_API}{path}.json", timeout=20)
    r.raise_for_status()
    return r.json()


def is_ai_flavored(title: str, text: str | None) -> bool:
    blob = (title + " " + (text or "")).lower()
    return any(kw in blob for kw in AI_KEYWORDS)


def run(*, max_items: int = 60, lists: list[str], skip_classify: bool = False,
        model: str = "pa/gpt-5.5") -> None:
    conn = dbmod.connect()
    seen_ids: set[int] = set()
    for which in lists:
        ids = _get(f"/{which}stories") or []
        for hn_id in ids[:max_items]:
            if hn_id in seen_ids:
                continue
            seen_ids.add(hn_id)
            story = _get(f"/item/{hn_id}")
            if not isinstance(story, dict):
                continue
            title = story.get("title") or ""
            text = story.get("text") or ""
            url = story.get("url") or f"https://news.ycombinator.com/item?id={hn_id}"
            if story.get("type") != "story":
                continue
            if not is_ai_flavored(title, text):
                continue
            score = int(story.get("score") or 0)
            descendants = int(story.get("descendants") or 0)
            item_id = dbmod.upsert_item(
                conn,
                source="hn",
                source_id=str(hn_id),
                title=title,
                url=url,
                owner=story.get("by"),
                description=text[:500] if text else None,
                raw={"score": score, "descendants": descendants, "type": story.get("type"),
                     "list": which},
            )
            dbmod.add_metric(conn, item_id, "hn_points", float(score))
            dbmod.add_metric(conn, item_id, "hn_comments", float(descendants))
            if not skip_classify and dbmod.needs_tagging(conn, item_id, model):
                payload = {
                    "title": title, "url": url, "language": "",
                    "description": text[:800] if text else "",
                    "topics": [], "readme_excerpt": "",
                }
                try:
                    tag = classify(payload, model=model)
                    dbmod.set_tag(conn, item_id, bucket=tag["bucket"], audience=tag["audience"],
                                  free_tags=tag["free_tags"], rationale=tag["rationale"],
                                  model=tag["model"])
                    print(f"  + hn:{hn_id} '{title[:60]}' → {tag['bucket']}/{tag['audience']}")
                except Exception as e:
                    print(f"  ! classify hn:{hn_id} failed: {e}", file=sys.stderr)
            conn.commit()
            time.sleep(0.2)
    conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lists", nargs="+", default=["top", "best"])
    ap.add_argument("--max", type=int, default=60)
    ap.add_argument("--skip-classify", action="store_true")
    args = ap.parse_args()
    run(max_items=args.max, lists=args.lists, skip_classify=args.skip_classify)


if __name__ == "__main__":
    main()
