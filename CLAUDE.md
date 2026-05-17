# gh-trending-radar — for Claude Code sessions

This repo's purpose: **scout fast-rising open-source projects to help spot AI-agent-era startup opportunities**. The owner (gongyibob) is a SaaS founder evaluating where to go next. Optimize all suggestions toward _insight density_, not "more data."

When invoked here, your job is twofold:
1. **Keep the pipeline healthy** (fetch, classify, report, schedule).
2. **Help with ad-hoc analysis** — the owner will ask things like "what bucket grew fastest this week" or "find me consumer-facing agent products under 30 days old" — query `db.sqlite` directly with SQLite and answer.

## Repo layout

```
scripts/
  db.py           # SQLite layer (schema + helpers). Read this before SQL.
  paigod.py       # Novita paigod proxy wrapper. pa/gpt-5.5 has beta limits — no temperature.
  classify.py     # LLM tagging: bucket + audience + free_tags + rationale
  fetch_github.py # github.com/trending scrape + GitHub API enrich + classify
  report.py       # render reports/YYYY-MM-DD.md from SQLite
  # (future: fetch_hn.py, fetch_yc.py, fetch_ph.py, weekly_digest.py)
config.yaml       # filter knobs (new_repo_days, min_stars, buckets, audience labels)
db.sqlite         # source of truth — NOT committed (gitignored)
reports/          # daily markdown reports (committed)
reports/weekly/   # weekly LLM digests
notes/            # owner's manual idea log — read these when synthesizing
dashboard/        # Next.js dashboard (future) — reads dumped data.json
.github/workflows/ # cron via GitHub Actions
```

## SQLite schema (single source of truth)

All sources share these tables — `items.source ∈ {github_trending, hn, yc, product_hunt}`.

- **items**: `id, source, source_id, title, url, owner, owner_type, language, description, license, topics_json, readme_excerpt, repo_created_at, first_seen_at, last_seen_at, raw_json`
- **metrics**: time-series of any numeric signal. `item_id, metric, value, snapshot_at`. `metric ∈ {stars, forks, hn_points, ph_votes, ...}`
- **trending_appearances**: `item_id, window, rank, stars_today, seen_at` — every time a repo appears on github.com/trending we log it
- **tags**: LLM classification. `item_id, bucket, audience, free_tags (JSON array), rationale, model, tagged_at`
- **notes**: free-form owner notes, optionally attached to an item

## Buckets (fixed taxonomy)

`ai-agent`, `ai-app`, `ai-infra`, `devtool`, `data`, `security`, `web-framework`, `other`

`audience`: `B` (businesses), `C` (consumers), `both`, `dev` (developers as users)

## Useful queries to start any analysis

```sql
-- Top fast risers in last 7 days
SELECT i.source_id, i.description, t.bucket, t.audience,
       MAX(m.value) - MIN(m.value) AS delta_stars
FROM items i
JOIN metrics m ON m.item_id = i.id AND m.metric = 'stars'
LEFT JOIN tags t ON t.item_id = i.id
WHERE m.snapshot_at >= datetime('now', '-7 days')
GROUP BY i.id
ORDER BY delta_stars DESC
LIMIT 20;

-- Bucket distribution by audience
SELECT bucket, audience, COUNT(*) FROM tags
GROUP BY bucket, audience ORDER BY bucket;

-- Brand-new repos (under 30 days) that already trended
SELECT i.source_id, i.repo_created_at, i.description, t.bucket, t.audience
FROM items i LEFT JOIN tags t ON t.item_id = i.id
WHERE i.source='github_trending'
  AND julianday('now') - julianday(i.repo_created_at) < 30
ORDER BY i.first_seen_at DESC;
```

## How to run

```bash
# one-time
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# daily pipeline (locally or in Actions)
.venv/bin/python scripts/fetch_github.py
.venv/bin/python scripts/report.py
```

API key for paigod proxy lives in `~/.config/paigod/credentials` (chmod 600) locally, and in repo Secrets as `PAIGOD_API_KEY` (+ `PAIGOD_BASE_URL`, `PAIGOD_DEFAULT_MODEL`) for Actions.

## Style hints

- **Bias to insight, not features.** Owner cares about "what could I build?" — when summarizing, group by _gap or pattern_, not by language or stars.
- **Surface to-B vs to-C deliberately.** SaaS background → strong bias toward B; explicitly flag interesting C plays.
- **Prefer SQL over rebuilding state in Python** when answering ad-hoc questions. The schema is designed to be queryable.
- **README excerpts matter more than descriptions** — descriptions lie, READMEs leak intent.
