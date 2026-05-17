"""Thin wrapper around Novita's paigod proxy (OpenAI-compatible chat/completions)."""
from __future__ import annotations
import json
import os
import time
from pathlib import Path

import requests
from dotenv import dotenv_values

CREDENTIALS_PATH = Path.home() / ".config" / "paigod" / "credentials"


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if CREDENTIALS_PATH.exists():
        env.update({k: v for k, v in dotenv_values(CREDENTIALS_PATH).items() if v is not None})
    for key in ("PAIGOD_API_KEY", "PAIGOD_BASE_URL", "PAIGOD_DEFAULT_MODEL"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


_ENV = _load_env()


BETA_LIMITED_MODELS = {"pa/gpt-5.5"}


def chat(messages: list[dict], *, model: str | None = None, max_tokens: int = 512,
         temperature: float | None = None, response_format: dict | None = None,
         retries: int = 3, timeout: int = 60) -> str:
    env = _load_env()
    api_key = env.get("PAIGOD_API_KEY")
    base_url = env.get("PAIGOD_BASE_URL", "https://apiproxy.paigod.work/v1")
    model = model or env.get("PAIGOD_DEFAULT_MODEL", "pa/gpt-5.5")
    if not api_key:
        raise RuntimeError("PAIGOD_API_KEY missing; set in env or ~/.config/paigod/credentials")

    payload: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if model not in BETA_LIMITED_MODELS and temperature is not None:
        payload["temperature"] = temperature
    if response_format is not None:
        payload["response_format"] = response_format

    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=timeout,
            )
            if not resp.ok:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except (requests.RequestException, RuntimeError, KeyError, ValueError) as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"paigod chat failed after {retries} retries: {last_err}")


def chat_json(messages: list[dict], **kwargs) -> dict:
    """Ask the model for JSON and parse it. Falls back to extracting the first {...} block."""
    text = chat(messages, response_format={"type": "json_object"}, **kwargs)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise
