"""Fetch Product Hunt AI category Atom feed, classify each entry (B/C/both/dev).

We don't get vote counts without OAuth; we rely on PH's editorial AI category and
LLM classification (especially audience B vs C) to surface signal.
"""
from __future__ import annotations
import argparse
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import db as dbmod  # noqa: E402
from classify import classify  # noqa: E402

PH_FEED = "https://www.producthunt.com/feed?category=ai"
UA = "gh-trending-radar/0.1"


def fetch_feed(url: str = PH_FEED) -> list[dict]:
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml-xml")
    out: list[dict] = []
    for entry in soup.find_all("entry"):
        tag_id = (entry.find("id").text if entry.find("id") else "").strip()
        m = re.search(r"Post/(\d+)", tag_id)
        if not m:
            continue
        post_id = m.group(1)
        title_el = entry.find("title")
        link_el = entry.find("link")
        content_el = entry.find("content")
        published_el = entry.find("published")
        title = title_el.text.strip() if title_el else ""
        link = link_el.get("href") if link_el else ""
        content_html = content_el.text if content_el else ""
        text = BeautifulSoup(content_html, "lxml").get_text(" ", strip=True)
        out.append({
            "post_id": post_id,
            "title": title,
            "url": link,
            "description": text[:600],
            "published": published_el.text.strip() if published_el else None,
        })
    return out


def run(*, skip_classify: bool = False, model: str = "pa/gpt-5.5") -> None:
    conn = dbmod.connect()
    entries = fetch_feed()
    print(f"[product_hunt] {len(entries)} entries")
    for e in entries:
        item_id = dbmod.upsert_item(
            conn,
            source="product_hunt",
            source_id=e["post_id"],
            title=e["title"],
            url=e["url"],
            description=e["description"],
            raw={"published": e["published"]},
        )
        if not skip_classify and dbmod.needs_tagging(conn, item_id, model):
            payload = {
                "title": e["title"], "url": e["url"], "language": "",
                "description": e["description"], "topics": [], "readme_excerpt": "",
            }
            try:
                tag = classify(payload, model=model)
                dbmod.set_tag(conn, item_id, bucket=tag["bucket"], audience=tag["audience"],
                              free_tags=tag["free_tags"], rationale=tag["rationale"],
                              model=tag["model"])
                print(f"  + ph:{e['post_id']} '{e['title'][:60]}' → {tag['bucket']}/{tag['audience']}")
            except Exception as ex:
                print(f"  ! classify ph:{e['post_id']} failed: {ex}", file=sys.stderr)
        conn.commit()
        time.sleep(0.2)
    conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-classify", action="store_true")
    args = ap.parse_args()
    run(skip_classify=args.skip_classify)


if __name__ == "__main__":
    main()
