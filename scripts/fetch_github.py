"""Fetch GitHub trending (daily/weekly/monthly), enrich via GitHub API, classify, persist."""
from __future__ import annotations
import argparse
import base64
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import db as dbmod  # noqa: E402
from classify import classify  # noqa: E402

TRENDING_BASE = "https://github.com/trending"
UA = "gh-trending-radar/0.1 (+https://github.com/gongyibob-ctrl/gh-trending-radar)"


def fetch_trending(window: str = "daily") -> list[dict]:
    """Scrape github.com/trending. window: daily | weekly | monthly."""
    url = TRENDING_BASE if window == "daily" else f"{TRENDING_BASE}?since={window}"
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    out: list[dict] = []
    for idx, art in enumerate(soup.select("article.Box-row"), start=1):
        h2 = art.select_one("h2 a")
        if not h2:
            continue
        slug = h2["href"].strip("/")  # owner/repo
        owner, _, repo = slug.partition("/")
        desc_el = art.select_one("p")
        description = desc_el.get_text(strip=True) if desc_el else ""
        lang_el = art.select_one("[itemprop='programmingLanguage']")
        language = lang_el.get_text(strip=True) if lang_el else None
        stars_today_text = ""
        for span in art.select("span.d-inline-block.float-sm-right"):
            stars_today_text = span.get_text(strip=True)
        m = re.search(r"([\d,]+)\s*stars\s*(today|this week|this month)", stars_today_text)
        stars_today = int(m.group(1).replace(",", "")) if m else None
        out.append({
            "slug": slug,
            "owner": owner,
            "repo": repo,
            "rank": idx,
            "description": description,
            "language": language,
            "stars_today": stars_today,
            "window": window,
        })
    return out


def gh_api(path: str) -> dict | list:
    """Call GitHub API via the authenticated gh CLI."""
    result = subprocess.run(
        ["gh", "api", path, "-H", "Accept: application/vnd.github+json"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh api {path} failed: {result.stderr[:300]}")
    import json as _json
    return _json.loads(result.stdout)


def fetch_repo_metadata(slug: str) -> dict | None:
    try:
        return gh_api(f"repos/{slug}")
    except RuntimeError as e:
        print(f"  ! metadata failed for {slug}: {e}", file=sys.stderr)
        return None


def fetch_readme_excerpt(slug: str, max_chars: int = 1500) -> str:
    try:
        data = gh_api(f"repos/{slug}/readme")
    except RuntimeError:
        return ""
    if not isinstance(data, dict) or "content" not in data:
        return ""
    try:
        raw = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    except Exception:
        return ""
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", raw)
    raw = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", raw)
    raw = re.sub(r"```[\s\S]*?```", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw[:max_chars]


def days_since(iso_ts: str | None) -> int | None:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - dt).days


def run(windows: list[str], *, new_repo_days: int = 180, min_stars: int = 100,
        skip_classify: bool = False, model: str = "pa/gpt-5.5") -> None:
    conn = dbmod.connect()
    seen_slugs: set[str] = set()
    appearances: list[tuple[str, str, int, int | None]] = []

    for window in windows:
        print(f"[trending {window}] fetching...")
        try:
            entries = fetch_trending(window)
        except Exception as e:
            print(f"  ! {window} scrape failed: {e}", file=sys.stderr)
            continue
        for entry in entries:
            appearances.append((entry["slug"], window, entry["rank"], entry["stars_today"]))
            seen_slugs.add(entry["slug"])

    print(f"[trending] unique slugs: {len(seen_slugs)}")
    processed = 0
    for slug in sorted(seen_slugs):
        meta = fetch_repo_metadata(slug)
        if not meta:
            continue
        created_at = meta.get("created_at")
        age_days = days_since(created_at)
        stars = meta.get("stargazers_count") or 0
        forks = meta.get("forks_count") or 0
        if stars < min_stars:
            continue
        if age_days is not None and age_days > new_repo_days:
            print(f"  - skip {slug} (too old, {age_days}d)")
            continue
        readme = fetch_readme_excerpt(slug)
        owner_info = meta.get("owner") or {}
        item_id = dbmod.upsert_item(
            conn,
            source="github_trending",
            source_id=slug,
            title=meta.get("full_name") or slug,
            url=meta.get("html_url") or f"https://github.com/{slug}",
            owner=owner_info.get("login"),
            owner_type=owner_info.get("type"),
            language=meta.get("language"),
            description=meta.get("description"),
            license=(meta.get("license") or {}).get("spdx_id"),
            topics=meta.get("topics") or [],
            readme_excerpt=readme,
            repo_created_at=created_at,
            raw={
                "stars": stars, "forks": forks,
                "open_issues": meta.get("open_issues_count"),
                "homepage": meta.get("homepage"),
                "archived": meta.get("archived"),
                "fork": meta.get("fork"),
            },
        )
        dbmod.add_metric(conn, item_id, "stars", float(stars))
        dbmod.add_metric(conn, item_id, "forks", float(forks))

        if not skip_classify and dbmod.needs_tagging(conn, item_id, model):
            item_for_classify = {
                "title": slug,
                "url": meta.get("html_url"),
                "language": meta.get("language"),
                "description": meta.get("description"),
                "topics": meta.get("topics") or [],
                "readme_excerpt": readme,
            }
            try:
                tag = classify(item_for_classify, model=model)
                dbmod.set_tag(
                    conn, item_id,
                    bucket=tag["bucket"], audience=tag["audience"],
                    free_tags=tag["free_tags"], rationale=tag["rationale"],
                    model=tag["model"],
                )
                print(f"  + {slug}  bucket={tag['bucket']} aud={tag['audience']} stars={stars} age={age_days}d")
            except Exception as e:
                print(f"  ! classify {slug} failed: {e}", file=sys.stderr)
        else:
            print(f"  = {slug}  stars={stars} age={age_days}d (cached or skip)")

        processed += 1
        conn.commit()
        time.sleep(0.3)

    cur = conn.cursor()
    for slug, window, rank, stars_today in appearances:
        row = cur.execute(
            "SELECT id FROM items WHERE source=? AND source_id=?",
            ("github_trending", slug),
        ).fetchone()
        if row:
            dbmod.add_trending_appearance(conn, row["id"], window, rank, stars_today)
    conn.commit()
    conn.close()
    print(f"[done] processed {processed} repos")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", nargs="+", default=["daily", "weekly", "monthly"])
    ap.add_argument("--new-repo-days", type=int, default=180)
    ap.add_argument("--min-stars", type=int, default=100)
    ap.add_argument("--skip-classify", action="store_true")
    ap.add_argument("--model", default=os.environ.get("PAIGOD_DEFAULT_MODEL", "pa/gpt-5.5"))
    args = ap.parse_args()
    run(args.windows, new_repo_days=args.new_repo_days, min_stars=args.min_stars,
        skip_classify=args.skip_classify, model=args.model)


if __name__ == "__main__":
    main()
