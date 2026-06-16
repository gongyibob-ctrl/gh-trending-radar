# gh-trending-radar

Idea-sourcing radar for AI-agent-era startup opportunities. Scrapes GitHub Trending
(+ HN/YC/Product Hunt later), enriches with GitHub API, classifies via LLM into
bucket × audience (B/C/both/dev), and emits a daily markdown digest plus
a Next.js dashboard.

See `CLAUDE.md` for schema and ad-hoc analysis hints — open this repo in Claude Code
and just ask.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/fetch_github.py    # scrape + classify
.venv/bin/python scripts/report.py          # write reports/YYYY-MM-DD.md
```

Set `PAIGOD_API_KEY` (and `PAIGOD_BASE_URL`, `PAIGOD_DEFAULT_MODEL`) via env or
`~/.config/paigod/credentials` (chmod 600). In GitHub Actions they come from repo
Secrets. `paigod` is just an OpenAI-compatible proxy — point `PAIGOD_BASE_URL` at
any OpenAI-compatible endpoint and it works.

## License

MIT — see [LICENSE](LICENSE).
