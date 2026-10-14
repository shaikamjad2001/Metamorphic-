"""Optional LLM layer (temperature 0). Used by the chat to plan a question and to word the answer from facts the
agents computed. It never produces the numbers and is never used by the metamorphic harness.

Configuration (environment or .env), first match wins:
  LLM_BASE_URL + LLM_MODEL [+ LLM_API_KEY]      any OpenAI-compatible server (Ollama, LM Studio, vLLM, ...)
  AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY + AZURE_OPENAI_DEPLOYMENT [+ AZURE_OPENAI_API_VERSION]
  OPENAI_API_KEY [+ OPENAI_MODEL]
  GOOGLE_API_KEY [+ GEMINI_MODEL]
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

import httpx

from backend import config

PARSE_SYSTEM = (
    "You convert a housing-market question about the Dallas, Texas metro into JSON search criteria. "
    "Return ONLY a JSON object with any of these keys: zipcodes (list of 5-digit strings), cities (list), "
    "tiers (subset of Entry, Value, Mid-Market, Upper, Luxury), min_price, max_price (USD numbers), "
    "min_sqft, max_sqft, window_end (YYYY-MM, the last month of the 12-month window). Omit unknown keys."
)


def _load_env() -> None:
    for path in (os.path.join(config.ROOT, ".env"), os.path.join(config.ROOT, "backend", ".env")):
        if not os.path.exists(path):
            continue
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("export "):
                    line = line[7:]
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    v = v.strip().strip('"').strip("'")
                    if v:
                        os.environ.setdefault(k.strip(), v)


_load_env()


def provider() -> Optional[str]:
    e = os.environ
    if e.get("LLM_BASE_URL") and e.get("LLM_MODEL"):
        return f"openai-compatible:{e['LLM_MODEL']}"
    if e.get("AZURE_OPENAI_ENDPOINT") and e.get("AZURE_OPENAI_API_KEY") and e.get("AZURE_OPENAI_DEPLOYMENT"):
        return f"azure:{e['AZURE_OPENAI_DEPLOYMENT']}"
    if e.get("OPENAI_API_KEY"):
        return f"openai:{e.get('OPENAI_MODEL', 'gpt-4o-mini')}"
    if e.get("GOOGLE_API_KEY"):
        return f"gemini:{e.get('GEMINI_MODEL', 'gemini-2.0-flash')}"
    return None


def extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}


def complete(system: str, user: str, json_mode: bool = False, timeout: float = 30.0) -> str:
    """One chat completion at temperature 0. Raises on any provider error; callers fall back to rules."""
    p = provider()
    if p is None:
        raise RuntimeError("no LLM configured")
    e = os.environ
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if p.startswith("gemini"):
        model = e.get("GEMINI_MODEL", "gemini-2.0-flash")
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"parts": [{"text": user}]}],
                "generationConfig": {"temperature": 0, **({"responseMimeType": "application/json"} if json_mode else {})}}
        r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                       params={"key": e["GOOGLE_API_KEY"]}, json=body, timeout=timeout)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]

    body: dict = {"temperature": 0, "messages": messages}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if p.startswith("azure"):
        version = e.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
        url = (f"{e['AZURE_OPENAI_ENDPOINT'].rstrip('/')}/openai/deployments/{e['AZURE_OPENAI_DEPLOYMENT']}"
               f"/chat/completions?api-version={version}")
        headers = {"api-key": e["AZURE_OPENAI_API_KEY"]}
    elif p.startswith("openai:"):
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {e['OPENAI_API_KEY']}"}
        body["model"] = e.get("OPENAI_MODEL", "gpt-4o-mini")
    else:
        url = e["LLM_BASE_URL"].rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {e['LLM_API_KEY']}"} if e.get("LLM_API_KEY") else {}
        body["model"] = e["LLM_MODEL"]
        body["seed"] = 42
    r = httpx.post(url, json=body, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def parse_with_llm(query: str, timeout: float = 20.0) -> Optional[dict]:
    if provider() is None:
        return None
    return extract_json(complete(PARSE_SYSTEM, query, json_mode=True, timeout=timeout))
