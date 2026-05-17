"""LLM tagging for an item — bucket + audience + free tags + one-line rationale."""
from __future__ import annotations
import json
from typing import Any

from paigod import chat_json

SYSTEM = """You categorize trending software projects to help a SaaS founder spot AI-agent-era startup opportunities.

Return a single JSON object with these keys:
- bucket: one of ["ai-agent", "ai-infra", "ai-app", "devtool", "web-framework", "data", "security", "other"]
  - ai-agent: autonomous/multi-step LLM systems, agent frameworks, computer-use, browser agents
  - ai-infra: model serving, inference, training, RAG infra, vector DBs, eval tooling
  - ai-app: end-user products that ship AI (chatbots, content tools, copilots packaged as a product)
  - devtool: tooling for engineers, CLIs, build/test/lint/IDE
  - web-framework: frontend/backend frameworks, UI libraries
  - data: databases, analytics, ETL, pipelines
  - security: pentesting, scanning, secrets, auth
  - other: anything not clearly fitting the above
- audience: one of ["B", "C", "both", "dev"]
  - B: businesses buy and use it (sales, ops, finance, internal tools)
  - C: individual consumers use it (creators, students, lifestyle)
  - both: serves both meaningfully
  - dev: developers as end users (libraries, dev tools)
- free_tags: array of 2-4 short lowercase keywords specific enough to be useful (e.g. ["browser-agent", "playwright", "self-hosted"])
- rationale: one sentence (<=140 chars) explaining the call, ideally noting what gap or pattern this represents

Be decisive — pick the closest bucket even if imperfect. Prefer ai-app over ai-infra when the project is shipped as a usable product."""


def build_user_prompt(item: dict[str, Any]) -> str:
    parts = [
        f"Name: {item.get('title', '')}",
        f"URL: {item.get('url', '')}",
        f"Language: {item.get('language') or 'n/a'}",
        f"Description: {item.get('description') or 'n/a'}",
    ]
    topics = item.get("topics") or []
    if topics:
        parts.append(f"Topics: {', '.join(topics)}")
    readme = (item.get("readme_excerpt") or "").strip()
    if readme:
        parts.append(f"README excerpt:\n{readme[:600]}")
    return "\n".join(parts)


def classify(item: dict[str, Any], *, model: str = "pa/gpt-5.5") -> dict[str, Any]:
    user = build_user_prompt(item)
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user},
    ]
    result = chat_json(messages, model=model, max_tokens=300, temperature=0.1)
    bucket = result.get("bucket", "other")
    audience = result.get("audience", "dev")
    free_tags = result.get("free_tags") or []
    if isinstance(free_tags, str):
        free_tags = [t.strip() for t in free_tags.split(",") if t.strip()]
    return {
        "bucket": bucket,
        "audience": audience,
        "free_tags": [str(t).lower() for t in free_tags][:6],
        "rationale": (result.get("rationale") or "")[:200],
        "model": model,
    }


if __name__ == "__main__":
    import sys
    sample = {
        "title": "browser-use",
        "url": "https://github.com/browser-use/browser-use",
        "language": "Python",
        "description": "Make websites accessible for AI agents",
        "topics": ["agent", "browser-automation", "llm"],
        "readme_excerpt": "Browser-use is the easiest way to connect your AI agents with the browser.",
    }
    print(json.dumps(classify(sample), ensure_ascii=False, indent=2))
