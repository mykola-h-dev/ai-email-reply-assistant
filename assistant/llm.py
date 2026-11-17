"""Minimal LLM client for Google Gemini or OpenAI, using only `requests`.

The provider is chosen from environment variables:
  - GEMINI_API_KEY  -> Google Gemini (model from GEMINI_MODEL, default gemini-2.5-flash)
  - OPENAI_API_KEY  -> OpenAI Chat Completions (model from OPENAI_MODEL, default gpt-4o-mini)
If neither is set, `is_available()` returns False and callers fall back to offline mode.
Keys are never logged or printed.
"""

import os

import requests

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
TIMEOUT_SECONDS = 30


def provider_name():
    """Return 'gemini', 'openai' or None depending on which key is configured."""
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return None


def is_available():
    return provider_name() is not None


def generate(system_prompt, user_prompt, temperature=0.2):
    """Send one prompt to the configured provider and return the reply text.

    Raises RuntimeError when no key is configured or the API call fails,
    so the caller can decide to fall back to offline mode.
    """
    provider = provider_name()
    try:
        if provider == "gemini":
            return _gemini(system_prompt, user_prompt, temperature)
        if provider == "openai":
            return _openai(system_prompt, user_prompt, temperature)
    except requests.RequestException as exc:  # network errors, timeouts
        raise RuntimeError(f"LLM request failed: {type(exc).__name__}") from exc
    raise RuntimeError("No LLM API key configured")


def _gemini(system_prompt, user_prompt, temperature):
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    headers = {"x-goog-api-key": os.environ["GEMINI_API_KEY"], "Content-Type": "application/json"}
    resp = requests.post(GEMINI_URL.format(model=model), json=body, headers=headers, timeout=TIMEOUT_SECONDS)
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini API error {resp.status_code}")
    data = resp.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError) as exc:
        raise RuntimeError("Unexpected Gemini response format") from exc


def _openai(system_prompt, user_prompt, temperature):
    body = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    headers = {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}
    resp = requests.post(OPENAI_URL, json=body, headers=headers, timeout=TIMEOUT_SECONDS)
    if resp.status_code != 200:
        raise RuntimeError(f"OpenAI API error {resp.status_code}")
    return resp.json()["choices"][0]["message"]["content"].strip()
