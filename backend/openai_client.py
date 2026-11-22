"""
Minimal OpenAI chat-completions client (REST API).

Used by ai_provider.OpenAIProvider, cost_guard.OpenAIClassifier, tour_guide_service and voice/agent.py.
Settings (backend/.env):
  OPENAI_API_KEY           required
  OPENAI_MODEL             default "gpt-4.1-mini"
  OPENAI_REASONING_EFFORT  optional override for every call (none|minimal|low|medium|high|xhigh|max);
                           unset = each caller's own value, which is "low"

reasoning_effort is sent on every call. A model that does not take it (OpenAI answers HTTP 400,
code unsupported_parameter) is retried once without it, then remembered for this process.
"""
import json as _json
import logging
import os
from typing import Any, Dict, List, Optional, Set

import requests

logger = logging.getLogger("voyageai.openai")

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"

# Models that rejected reasoning_effort. Per process; the skip is logged once per model.
_NO_REASONING_EFFORT: Set[str] = set()


class LLMError(RuntimeError):
    """OpenAI call failed (missing key, HTTP error, empty or cut-off answer)."""


class LLMTransient(LLMError):
    """Worth one retry: a 5xx, a timeout, or a malformed tool call."""


class LLMRateLimited(LLMError):
    """OpenAI returned 429: the account's rate limit was hit."""


def llm_model() -> str:
    return (os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL).strip()


def _api_key() -> str:
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise LLMError("OPENAI_API_KEY is not set")
    return key


def _effort(requested: Optional[str]) -> Optional[str]:
    override = (os.getenv("OPENAI_REASONING_EFFORT") or "").strip().lower()
    return override or requested


def _error_fields(res) -> Dict[str, str]:
    """The provider's error code and param only; never the message, which can quote the user."""
    try:
        err = res.json().get("error")
        if isinstance(err, dict):
            # "effort" is a yes/no match on the message (some models answer code=null, param=null, "Unrecognized
            # request argument supplied: reasoning_effort"). The message text itself is never returned or logged.
            return {"code": str(err.get("code") or "")[:40], "param": str(err.get("param") or "")[:40],
                    "effort": "reasoning_effort" in str(err.get("message") or "")}
    except Exception:
        return {"code": "non_json_body", "param": "", "effort": False}
    return {"code": "", "param": "", "effort": False}


def _post(body: Dict[str, Any], timeout: float, effort: Optional[str], *, request_error=LLMError):
    """POST one chat request. Adds reasoning_effort, and retries once without it if the model rejects it."""
    api_key = _api_key()
    model = body["model"]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    send_effort = effort if (effort and model not in _NO_REASONING_EFFORT) else None
    for _attempt in range(2):
        payload = dict(body)
        if send_effort:
            payload["reasoning_effort"] = send_effort
        try:
            res = requests.post(OPENAI_CHAT_URL, headers=headers, json=payload, timeout=timeout)
        except requests.RequestException as exc:
            raise request_error(f"OpenAI request failed: {type(exc).__name__}") from exc

        if res.status_code == 400 and send_effort:
            fields = _error_fields(res)
            if fields["code"] == "unsupported_parameter" or fields["param"] == "reasoning_effort" or fields["effort"]:
                _NO_REASONING_EFFORT.add(model)
                logger.warning("[OPENAI] %s does not accept reasoning_effort; sending without it from now on", model)
                send_effort = None
                continue
        return res
    return res  # pragma: no cover (the loop always returns)


def _raise_for_status(res, *, transient_5xx: bool) -> None:
    if res.status_code == 200:
        return
    if res.status_code == 429:
        raise LLMRateLimited("OpenAI rate limit reached")
    fields = _error_fields(res)
    msg = f"OpenAI HTTP {res.status_code} {fields['code']}".strip()
    if transient_5xx and res.status_code >= 500:
        raise LLMTransient(msg)
    raise LLMError(msg)


def chat(
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0.2,
    timeout: float = 30,
    response_format: Optional[Dict[str, Any]] = None,
    max_completion_tokens: Optional[int] = None,
    reasoning_effort: Optional[str] = "low",
) -> str:
    """Returns the assistant message text. Raises LLMError / LLMRateLimited."""
    body: Dict[str, Any] = {"model": llm_model(), "messages": messages, "temperature": temperature}
    if response_format:
        body["response_format"] = response_format
    if max_completion_tokens:
        body["max_completion_tokens"] = max_completion_tokens

    res = _post(body, timeout, _effort(reasoning_effort))
    _raise_for_status(res, transient_5xx=False)

    try:
        choice = res.json()["choices"][0]
        content = (choice.get("message") or {}).get("content") or ""
    except (ValueError, KeyError, IndexError) as exc:
        raise LLMError("OpenAI returned an unexpected response") from exc
    if choice.get("finish_reason") not in (None, "stop"):
        raise LLMError(f"OpenAI answer incomplete ({choice.get('finish_reason')})")
    if not content.strip():
        raise LLMError("OpenAI returned an empty answer")
    return content.strip()


def chat_tools(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    *,
    tool_choice: Any = "auto",
    temperature: float = 0.2,
    timeout: float = 8,
    reasoning_effort: Optional[str] = "low",
) -> Dict[str, Any]:
    """
    One chat call with function calling ("tools").
    Returns {"content": str | None, "tool_calls": [{"name": str, "arguments": dict}]}.
    Raises LLMError / LLMTransient / LLMRateLimited; a tool call with bad JSON arguments is LLMTransient.
    Error messages carry the status only, never the request or response text (voice: no words in logs).
    """
    body: Dict[str, Any] = {
        "model": llm_model(),
        "messages": messages,
        "tools": tools,
        "tool_choice": tool_choice,
        "temperature": temperature,
    }
    res = _post(body, timeout, _effort(reasoning_effort), request_error=LLMTransient)
    _raise_for_status(res, transient_5xx=True)

    try:
        choice = res.json()["choices"][0]
        message = choice.get("message") or {}
    except (ValueError, KeyError, IndexError) as exc:
        raise LLMError("OpenAI returned an unexpected response") from exc
    if choice.get("finish_reason") not in (None, "stop", "tool_calls"):
        raise LLMError(f"OpenAI answer incomplete ({choice.get('finish_reason')})")

    calls = []
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        raw_args = fn.get("arguments") or "{}"
        try:
            args = _json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except (ValueError, TypeError) as exc:
            raise LLMTransient("OpenAI tool call had malformed arguments") from exc
        if not isinstance(args, dict):
            raise LLMError("OpenAI tool call arguments were not an object")
        calls.append({"name": fn.get("name") or "", "arguments": args})

    content = message.get("content")
    content = content.strip() if isinstance(content, str) and content.strip() else None
    if not calls and not content:
        raise LLMError("OpenAI returned neither text nor a tool call")
    return {"content": content, "tool_calls": calls}


def chat_json(prompt: str, *, temperature: float = 0.2, timeout: float = 30,
              reasoning_effort: Optional[str] = "low") -> str:
    """One user prompt in, a JSON string out (JSON mode)."""
    return chat(
        [{"role": "user", "content": prompt}],
        temperature=temperature,
        timeout=timeout,
        response_format={"type": "json_object"},
        reasoning_effort=reasoning_effort,
    )
