"""
Minimal Groq chat-completions client (OpenAI-compatible REST API).

Used by ai_provider.GroqProvider and cost_guard.GroqClassifier.
Settings (backend/.env):
  GROQ_API_KEY   required
  GROQ_MODEL     default "openai/gpt-oss-120b"
"""
import os
from typing import Any, Dict, List, Optional

import requests

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"


class GroqError(RuntimeError):
    """Groq call failed (missing key, HTTP error, empty or cut-off answer)."""


class GroqRateLimited(GroqError):
    """Groq returned 429: the account's free-tier limit was hit."""


def groq_model() -> str:
    return (os.getenv("GROQ_MODEL") or DEFAULT_GROQ_MODEL).strip()


def groq_chat(
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0.2,
    timeout: float = 30,
    response_format: Optional[Dict[str, Any]] = None,
    max_completion_tokens: Optional[int] = None,
    reasoning_effort: Optional[str] = "low",
) -> str:
    """Returns the assistant message text. Raises GroqError / GroqRateLimited."""
    api_key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not api_key:
        raise GroqError("GROQ_API_KEY is not set")

    model = groq_model()
    body: Dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
    if response_format:
        body["response_format"] = response_format
    if max_completion_tokens:
        body["max_completion_tokens"] = max_completion_tokens
    if reasoning_effort and "gpt-oss" in model:
        body["reasoning_effort"] = reasoning_effort

    try:
        res = requests.post(
            GROQ_CHAT_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise GroqError(f"Groq request failed: {type(exc).__name__}") from exc

    if res.status_code == 429:
        raise GroqRateLimited("Groq rate limit reached")
    if res.status_code != 200:
        raise GroqError(f"Groq HTTP {res.status_code}: {res.text[:160]}")

    try:
        choice = res.json()["choices"][0]
        content = (choice.get("message") or {}).get("content") or ""
    except (ValueError, KeyError, IndexError) as exc:
        raise GroqError("Groq returned an unexpected response") from exc
    if choice.get("finish_reason") not in (None, "stop"):
        raise GroqError(f"Groq answer incomplete ({choice.get('finish_reason')})")
    if not content.strip():
        raise GroqError("Groq returned an empty answer")
    return content.strip()


def groq_json(prompt: str, *, temperature: float = 0.2, timeout: float = 30) -> str:
    """One user prompt in, a JSON string out (Groq JSON mode)."""
    return groq_chat(
        [{"role": "user", "content": prompt}],
        temperature=temperature,
        timeout=timeout,
        response_format={"type": "json_object"},
    )
