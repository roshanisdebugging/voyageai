"""
OpenAI client + gpt-transcribe STT checks. HTTP is simulated; no real calls, no DB, no Redis.
Run from backend/: python -m tests.test_openai_client
"""
import os
import sys
from pathlib import Path
from unittest import mock

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
for k in ("OPENAI_MODEL", "OPENAI_REASONING_EFFORT", "VOICE_STT_MODEL", "VOICE_STT_LANGUAGES", "VOICE_STT_PROMPT",
          "VOICE_STT_PROVIDER"):
    os.environ.pop(k, None)
os.environ["OPENAI_API_KEY"] = "test-key-not-real"

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

import openai_client  # noqa: E402
from voice import stt  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


class Resp:
    def __init__(self, status, body):
        self.status_code, self._b = status, body
        self.text = "body with the user's words"

    def json(self):
        return self._b


OK_TEXT = Resp(200, {"choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}]})
MSG = [{"role": "user", "content": "x"}]


def reset():
    openai_client._NO_REASONING_EFFORT.clear()
    os.environ.pop("OPENAI_REASONING_EFFORT", None)
    os.environ.pop("OPENAI_MODEL", None)


# ---------------- chat: URL, key, model, reasoning_effort
reset()
calls = []


def ok_post(url, headers=None, json=None, timeout=None):
    calls.append((url, headers, json))
    return OK_TEXT


with mock.patch.object(openai_client.requests, "post", ok_post):
    out = openai_client.chat(MSG)
url, headers, body = calls[-1]
check("chat returns the text", out == "hello")
check("chat posts to api.openai.com chat completions", url == "https://api.openai.com/v1/chat/completions", url)
check("chat sends the key", headers["Authorization"] == "Bearer test-key-not-real")
check("default model is gpt-4.1-mini", body["model"] == "gpt-4.1-mini", body["model"])
check("gpt-4.1-mini never gets reasoning_effort (decided up front, no wasted request)",
      "reasoning_effort" not in body and len(calls) == 1, body)

reset()
os.environ["OPENAI_MODEL"] = "gpt-5-mini"
with mock.patch.object(openai_client.requests, "post", ok_post):
    openai_client.chat(MSG)
check("OPENAI_MODEL overrides the model", calls[-1][2]["model"] == "gpt-5-mini")
check("a reasoning model (gpt-5-mini) gets reasoning_effort=low", calls[-1][2].get("reasoning_effort") == "low")

reset()
os.environ["OPENAI_MODEL"] = "gpt-5-mini"
os.environ["OPENAI_REASONING_EFFORT"] = "medium"
with mock.patch.object(openai_client.requests, "post", ok_post):
    openai_client.chat(MSG, reasoning_effort="low")
check("OPENAI_REASONING_EFFORT overrides the caller's value", calls[-1][2].get("reasoning_effort") == "medium")

reset()
os.environ["OPENAI_REASONING_EFFORT"] = "low"
n_before = len(calls)
with mock.patch.object(openai_client.requests, "post", ok_post):
    openai_client.chat_json("x")
check("OPENAI_REASONING_EFFORT=low set + gpt-4.1-mini: still not sent, one request",
      "reasoning_effort" not in calls[-1][2] and len(calls) == n_before + 1, calls[-1][2])
check("supports_reasoning_effort: o-series, gpt-5, gpt-oss yes; gpt-4.1 / gpt-4o / llama no",
      all(openai_client.supports_reasoning_effort(m) for m in ("o4-mini", "o3", "gpt-5-mini", "openai/gpt-oss-120b"))
      and not any(openai_client.supports_reasoning_effort(m) for m in ("gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini",
                                                                        "llama-3.3-70b-versatile", "")))

reset()
os.environ.pop("OPENAI_API_KEY")
try:
    openai_client.chat(MSG)
    check("missing key -> LLMError", False)
except openai_client.LLMError as e:
    check("missing key -> LLMError", "OPENAI_API_KEY" in str(e), str(e))
os.environ["OPENAI_API_KEY"] = "test-key-not-real"

# ---------------- safety net: a reasoning model rejects reasoning_effort anyway -> one retry without it, remembered
reset()
os.environ["OPENAI_MODEL"] = "o4-mini"
seen_bodies = []
rejecting = [Resp(400, {"error": {"code": "unsupported_parameter", "param": "reasoning_effort", "message": "user words"}})]


def reject_once(url, headers=None, json=None, timeout=None):
    seen_bodies.append(dict(json))
    if "reasoning_effort" in json:
        return rejecting[0]
    return OK_TEXT


with mock.patch.object(openai_client.requests, "post", reject_once):
    out = openai_client.chat(MSG)
    check("rejected reasoning_effort -> retried once without it, call succeeds",
          out == "hello" and len(seen_bodies) == 2 and "reasoning_effort" in seen_bodies[0] and "reasoning_effort" not in seen_bodies[1],
          seen_bodies)
    seen_bodies.clear()
    openai_client.chat(MSG)
    check("the next call for that model omits reasoning_effort (remembered)",
          len(seen_bodies) == 1 and "reasoning_effort" not in seen_bodies[0], seen_bodies)

# the shape gpt-4.1-mini used to answer with: code=null, param=null, only the message names the argument
reset()
os.environ["OPENAI_MODEL"] = "o4-mini"
seen_bodies = []
rejecting = [Resp(400, {"error": {"code": None, "param": None,
                                  "message": "Unrecognized request argument supplied: reasoning_effort"}})]
with mock.patch.object(openai_client.requests, "post", reject_once):
    out = openai_client.chat(MSG)
    check("code=null/param=null 400 naming reasoning_effort -> retried without it",
          out == "hello" and len(seen_bodies) == 2 and "reasoning_effort" not in seen_bodies[1], seen_bodies)

# another 400 is an error and is not retried
reset()
n = []


def other_400(url, headers=None, json=None, timeout=None):
    n.append(1)
    return Resp(400, {"error": {"code": "invalid_request_error", "message": "user words"}})


with mock.patch.object(openai_client.requests, "post", other_400):
    try:
        openai_client.chat(MSG)
        check("other 400 -> LLMError", False)
    except openai_client.LLMTransient:
        check("other 400 -> LLMError", False, "was transient")
    except openai_client.LLMError as e:
        check("other 400 -> LLMError, no retry, status and code only",
              len(n) == 1 and "400" in str(e) and "invalid_request_error" in str(e) and "user words" not in str(e), str(e))

# ---------------- status mapping
reset()
with mock.patch.object(openai_client.requests, "post", lambda *a, **k: Resp(429, {"error": {"code": "rate_limit_exceeded"}})):
    for fn, label in ((lambda: openai_client.chat(MSG), "chat"), (lambda: openai_client.chat_tools(MSG, []), "chat_tools")):
        try:
            fn()
            check(f"{label}: 429 -> LLMRateLimited", False)
        except openai_client.LLMRateLimited:
            check(f"{label}: 429 -> LLMRateLimited", True)
with mock.patch.object(openai_client.requests, "post", lambda *a, **k: Resp(500, {"error": {"code": "server_error"}})):
    try:
        openai_client.chat_tools(MSG, [])
        check("chat_tools: 5xx -> LLMTransient", False)
    except openai_client.LLMTransient:
        check("chat_tools: 5xx -> LLMTransient", True)
    try:
        openai_client.chat(MSG)
        check("chat: 5xx -> LLMError", False)
    except openai_client.LLMTransient:
        check("chat: 5xx -> LLMError", False, "was transient")
    except openai_client.LLMError:
        check("chat: 5xx -> LLMError", True)

# ---------------- gpt-transcribe STT
for k in ("VOICE_STT_MODEL", "VOICE_STT_LANGUAGES", "VOICE_STT_PROMPT"):
    os.environ.pop(k, None)
PCM = b"\x00\x00" * 1600
stt_calls = []


def stt_post(resp):
    def post(url, headers=None, files=None, data=None, timeout=None):
        stt_calls.append({"url": url, "headers": headers, "files": files, "data": data})
        return resp
    return post


with mock.patch.object(stt.requests, "post", stt_post(Resp(200, {"text": " namaste ", "languages": [{"code": "hi"}]}))):
    res = stt.get_stt().transcribe(PCM)
call = stt_calls[-1]
fields = dict(call["data"])
check("STT posts to the OpenAI transcriptions endpoint", call["url"] == "https://api.openai.com/v1/audio/transcriptions", call["url"])
check("STT sends the key", call["headers"]["Authorization"] == "Bearer test-key-not-real")
check("STT model is gpt-transcribe", fields["model"] == "gpt-transcribe", fields)
check("STT sends the Hinglish prompt", fields.get("prompt") == stt.DEFAULT_HINGLISH_PROMPT)
check("STT sends no response_format, language or languages[] by default",
      not any(k in fields for k in ("response_format", "language", "languages[]", "temperature")), fields)
check("STT sends a wav file", call["files"]["file"][0] == "speech.wav" and call["files"]["file"][1][:4] == b"RIFF")
check("STT result: text stripped, language from languages[0].code, provider/model",
      res.text == "namaste" and res.language == "hi" and res.provider == "openai" and res.model == "gpt-transcribe", res)

with mock.patch.object(stt.requests, "post", stt_post(Resp(200, {"text": "ok", "languages": []}))):
    res = stt.get_stt().transcribe(PCM)
check("empty languages -> language None", res.language is None and res.text == "ok")
with mock.patch.object(stt.requests, "post", stt_post(Resp(200, {"text": "ok"}))):
    res = stt.get_stt().transcribe(PCM)
check("no languages key -> language None", res.language is None)

os.environ["VOICE_STT_LANGUAGES"] = "hi, en"
with mock.patch.object(stt.requests, "post", stt_post(Resp(200, {"text": "ok", "languages": []}))):
    stt.get_stt().transcribe(PCM)
langs = [v for k, v in stt_calls[-1]["data"] if k == "languages[]"]
check("VOICE_STT_LANGUAGES=hi,en sends languages[] twice", langs == ["hi", "en"], stt_calls[-1]["data"])
os.environ.pop("VOICE_STT_LANGUAGES")

os.environ["VOICE_STT_PROMPT"] = ""
with mock.patch.object(stt.requests, "post", stt_post(Resp(200, {"text": "ok"}))):
    stt.get_stt().transcribe(PCM)
check("empty VOICE_STT_PROMPT sends no prompt", "prompt" not in dict(stt_calls[-1]["data"]))
os.environ.pop("VOICE_STT_PROMPT")

with mock.patch.object(stt.requests, "post", stt_post(Resp(429, {"error": {"code": "rate_limit_exceeded"}}))):
    try:
        stt.get_stt().transcribe(PCM)
        check("STT 429 -> STTRateLimited", False)
    except stt.STTRateLimited:
        check("STT 429 -> STTRateLimited", True)
with mock.patch.object(stt.requests, "post", stt_post(Resp(401, {"error": {"code": "invalid_api_key", "message": "Incorrect API key sk-xxx"}}))):
    try:
        stt.get_stt().transcribe(PCM)
        check("STT 401 -> STTError", False)
    except stt.STTRateLimited:
        check("STT 401 -> STTError", False, "was rate limited")
    except stt.STTError as e:
        check("STT 401 -> STTError with the status and code only",
              "401" in str(e) and "invalid_api_key" in str(e) and "sk-xxx" not in str(e), str(e))

os.environ.pop("OPENAI_API_KEY")
try:
    stt.get_stt().transcribe(PCM)
    check("STT missing key -> STTError", False)
except stt.STTError as e:
    check("STT missing key -> STTError", "OPENAI_API_KEY" in str(e), str(e))
os.environ["OPENAI_API_KEY"] = "test-key-not-real"

os.environ["VOICE_STT_PROVIDER"] = "groq"
try:
    stt.get_stt()
    check("unknown VOICE_STT_PROVIDER -> STTError", False)
except stt.STTError as e:
    check("unknown VOICE_STT_PROVIDER -> STTError", "Unknown VOICE_STT_PROVIDER" in str(e), str(e))
os.environ.pop("VOICE_STT_PROVIDER")

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
