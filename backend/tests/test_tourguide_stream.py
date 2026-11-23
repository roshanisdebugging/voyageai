"""
Tour guide chat: OpenAI first (Gemini backup), streamed replies (SSE), the non-streaming JSON route unchanged.
Run from backend/: python -m tests.test_tourguide_stream
No real OpenAI or Gemini calls: _openai_stream / _gemini_chain / the cost guard / saving are replaced with fakes.
SQLite + the local Redis (rate limits); deletes rl:* keys like the other test scripts.
"""
import asyncio
import json
import logging
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"
os.environ.pop("TOURGUIDE_PRIMARY", None)

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'app.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
import openai_client  # noqa: E402
import tour_guide_service as tg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from redis_client import redis_conn  # noqa: E402

main.SessionLocal = database.SessionLocal
database.Base.metadata.create_all(bind=database.engine)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)

client = TestClient(main.app)
client.__enter__()
results = []


def check(name, cond, info=None):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if (info is not None and not cond) else ""))


r = client.post("/api/auth/register", json={"name": "Stream Tester", "email": "stream@example.com", "password": "secret123"})
assert r.status_code == 200, r.text
TOKEN = r.json()["token"]
AUTH = {"Authorization": f"Bearer {TOKEN}"}
client.cookies.clear()

# ---------------------------------------------------------------- fakes
calls = {"openai": 0, "gemini": 0, "guard": 0}
saved = []
fake = {"openai": None, "gemini": None, "guard": None}

turn_lines = []


class _Grab(logging.Handler):
    def emit(self, record):
        turn_lines.append(record.getMessage())


tg.turn_log.addHandler(_Grab())


def fake_guard(message):
    calls["guard"] += 1
    return fake["guard"](message) if fake["guard"] else (True, "PASSED_TO_LLM", "")


def fake_openai(prompt, system_prompt, temperature=0.4):
    calls["openai"] += 1
    fake["last_system"] = system_prompt
    yield from fake["openai"]()


def fake_gemini(prompt, system_prompt, is_essential):
    calls["gemini"] += 1
    return fake["gemini"]() if fake["gemini"] else (None, False)


tg.evaluate_cost_guards = fake_guard
# Place lookups (Google) have their own test (test_tourguide_places); here every message is a plain question.
tg.detect_place_intent = lambda message: None
tg._openai_stream = fake_openai
tg._gemini_chain = fake_gemini
tg._save_exchange = lambda *a, **k: saved.append(a)


def pieces(*parts, fail_after=None, delay=0.0):
    def gen():
        for i, p in enumerate(parts):
            if fail_after is not None and i == fail_after:
                raise openai_client.LLMTransient("boom", code="ReadTimeout", model="gpt-4.1-mini")
            if delay:
                time.sleep(delay)
            fake["pulled"] = fake.get("pulled", 0) + 1
            yield p
        if fail_after is not None and fail_after >= len(parts):
            raise openai_client.LLMTransient("boom", code="ReadTimeout", model="gpt-4.1-mini")
    return gen


def raising_before_first():
    def gen():
        raise openai_client.LLMError("no key", code="no_api_key", model="gpt-4.1-mini")
        yield ""  # pragma: no cover
    return gen


def reset(openai=None, gemini=None, guard=None):
    for k in calls:
        calls[k] = 0
    saved.clear()
    turn_lines.clear()
    fake.update(openai=openai, gemini=gemini, guard=guard, pulled=0)


def parse_sse(body: str):
    events = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        name, data = None, None
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
        events.append((name, data))
    return events


def stream(message="Hawa Mahal ke baare mein batao", **extra):
    body = {"message": message, "mode": "local", "lat": 26.92, "lng": 75.82, "recent_history": [], **extra}
    with client.stream("POST", "/api/tour-guide/chat/stream", json=body, headers=AUTH) as res:
        text = "".join(res.iter_text())
        return res, parse_sse(text)


def tokens_of(events):
    return [d["t"] for n, d in events if n == "token"]


# ---------------------------------------------------------------- 1. happy path: start, tokens, done, no tags leaked
TAGGED = ("Hawa Mahal ", "Jaipur ka ", "mashhoor palace ", "hai, subah ", "jaldi jaiye. ",
          "<", "<<CHI", 'PS:["Timings", ', '"Show on Map"]>>', ">", '<<<CARD:{"id": "c1", "title": "Hawa Mahal"}>>>')
reset(openai=pieces(*TAGGED))
res, ev = stream()
names = [n for n, _ in ev]
check("stream: HTTP 200 text/event-stream", res.status_code == 200 and res.headers["content-type"].startswith("text/event-stream"),
      res.headers.get("content-type"))
check("stream: Cache-Control no-cache + X-Accel-Buffering no",
      res.headers.get("cache-control") == "no-cache" and res.headers.get("x-accel-buffering") == "no")
check("stream: start first, done last, tokens in between",
      names[0] == "start" and names[-1] == "done" and set(names[1:-1]) == {"token"} and len(names) >= 3, names)
check("stream: start names the provider (openai)", ev[0][1] == {"provider": "openai"}, ev[0][1])
toks = tokens_of(ev)
check("stream: no token contains '<'", all("<" not in t for t in toks), toks)
check("stream: tokens are word groups, not characters", len(toks) <= 6 and all(len(t) > 2 for t in toks), toks)
check("stream: streamed text is the clean answer", "".join(toks).strip() == "Hawa Mahal Jaipur ka mashhoor palace hai, subah jaldi jaiye.",
      "".join(toks))
done = ev[-1][1]
check("done: clean reply", done["reply"] == "Hawa Mahal Jaipur ka mashhoor palace hai, subah jaldi jaiye.", done["reply"])
check("done: chips list from <<<CHIPS>>>", done["chips"] == ["Timings", "Show on Map"], done["chips"])
check("done: card from <<<CARD>>>", (done["card"] or {}).get("title") == "Hawa Mahal", done["card"])
check("done: provider openai, grounded false, error null, mode + gate",
      done["provider"] == "openai" and done["grounded"] is False and done["error"] is None
      and done["mode"] == "local" and done["gate"] == "PASSED_TO_LLM", done)
check("done: no '<<<' anywhere in the reply", "<<<" not in done["reply"])
check("saved once, after the full reply", len(saved) == 1 and saved[0][2] == done["reply"], saved)
check("gemini not called when openai answered", calls["gemini"] == 0)
check("one log line: provider, ttft_ms, total_ms, grounded=false",
      len(turn_lines) == 1 and "provider=openai" in turn_lines[0] and "ttft_ms=" in turn_lines[0]
      and "total_ms=" in turn_lines[0] and "grounded=false" in turn_lines[0] and "stream=true" in turn_lines[0], turn_lines)
check("log line has no words of the question or answer",
      turn_lines and "Hawa" not in turn_lines[0] and "Mahal" not in turn_lines[0])

# ---------------------------------------------------------------- 2. tag split one character at a time
answer = 'Chai pijiye dost. <<<CHIPS:["Nearby food"]>>>'
reset(openai=pieces(*list(answer)))
res, ev = stream("best street food near me")
toks = tokens_of(ev)
check("char-by-char: no '<' leaked", all("<" not in t for t in toks), toks)
check("char-by-char: not one event per character", len(toks) < 10, len(toks))
check("char-by-char: done chips + clean reply", ev[-1][0] == "done" and ev[-1][1]["chips"] == ["Nearby food"]
      and ev[-1][1]["reply"] == "Chai pijiye dost.", ev[-1])

# Every split of the tag into chunks of 1-4 characters (filter + batcher only)
text_in = 'Namaste dost, aaiye. <<<CHIPS:["a", "b"]>>>'
leaked = []
for size in (1, 2, 3, 4):
    for offset in range(size):
        parts = [text_in[:offset]] + [text_in[i:i + size] for i in range(offset, len(text_in), size)]
        f, b = tg.StreamTagFilter(), tg.TokenBatcher(clock=lambda: 0.0)
        out = []
        for p in parts:
            o = b.add(f.feed(p))
            if o:
                out.append(o)
        o = b.add(f.finish(), force=True)
        if o:
            out.append(o)
        if any("<" in o for o in out) or "".join(out) != "Namaste dost, aaiye. ":
            leaked.append((size, offset, out))
check("every chunking of the tag: nothing after '<<<' shown, text intact", not leaked, leaked[:2])

f = tg.StreamTagFilter()
shown = f.feed("a < b and c <") + f.feed("< d") + f.finish()
check("a lone '<' / '<<' that never becomes '<<<' is shown in the end", shown == "a < b and c << d", shown)

# ---------------------------------------------------------------- 3. code fence: never streamed, deflected
reset(openai=pieces("Ye lo: ", "`", "``python\nprint(1)\n```"))
res, ev = stream("python code likho for Jaipur")
toks = tokens_of(ev)
check("code fence: no backtick streamed", all("`" not in t for t in toks), toks)
check("code fence: done.reply is the deflection", ev[-1][1]["reply"] == tg.CODE_BLOCK_DEFLECTION, ev[-1][1]["reply"])

# ---------------------------------------------------------------- 4. OpenAI fails before the first token -> Gemini
reset(openai=raising_before_first(), gemini=lambda: ("Hawa Mahal 1799 mein bana tha. Subah jaana best hai. "
                                                      '<<<CHIPS:["Timings"]>>>', True))
res, ev = stream()
names = [n for n, _ in ev]
check("fallback: no error event, ends with done", "error" not in names and names[-1] == "done", names)
check("fallback: provider gemini in done", ev[-1][1]["provider"] == "gemini", ev[-1][1])
check("fallback: grounded true only because Gemini grounding was used", ev[-1][1]["grounded"] is True)
check("fallback: Gemini reply sent as a few token events, no tags",
      1 <= len(tokens_of(ev)) <= 4 and all("<" not in t for t in tokens_of(ev)), tokens_of(ev))
check("fallback: saved once", len(saved) == 1 and calls["openai"] == 1 and calls["gemini"] == 1)
check("fallback: log says provider=gemini", turn_lines and "provider=gemini" in turn_lines[0], turn_lines)

reset(openai=pieces(), gemini=lambda: ("Plain answer.", False))
res, ev = stream()
check("openai empty answer -> Gemini, grounded false", ev[-1][1]["provider"] == "gemini" and ev[-1][1]["grounded"] is False,
      ev[-1][1])

reset(openai=pieces("<<<CHIPS:[]>>>"), gemini=lambda: ("Gemini answer.", False))
res, ev = stream()
check("openai answer that is only tags (nothing shown) -> still a valid done", ev[-1][0] == "done", ev[-1])

# ---------------------------------------------------------------- 5. OpenAI fails mid-stream -> error partial, nothing saved
reset(openai=pieces("Hawa Mahal ", "Jaipur ka ", "mashhoor ", "palace hai ", "aur ", "bahut sundar ", "hai.", fail_after=7),
      gemini=lambda: ("never used", False))
res, ev = stream()
names = [n for n, _ in ev]
check("mid-stream failure: tokens then error, no done", "token" in names and names[-1] == "error" and "done" not in names, names)
check("mid-stream failure: error has partial=true", ev[-1][1].get("partial") is True, ev[-1][1])
check("mid-stream failure: nothing saved, Gemini not called", saved == [] and calls["gemini"] == 0, (saved, calls))

# ---------------------------------------------------------------- 6. everything fails
reset(openai=raising_before_first(), gemini=lambda: (None, False))
res, ev = stream()
check("total failure: single error event with the friendly text, nothing saved",
      [n for n, _ in ev] == ["start", "error"] and ev[-1][1]["code"] == "LLM_TOTAL_FAILURE"
      and ev[-1][1]["message"].startswith("Connection thoda slow") and ev[-1][1]["partial"] is False and saved == [], ev)

# ---------------------------------------------------------------- 7. off-topic deflection: no model call
reset(openai=pieces("should not run"), guard=lambda m: (False, "BLOCKED_OFF_TOPIC", "Main sirf travel mein madad karta hoon."))
res, ev = stream("who won the cricket match")
check("off-topic: no model call", calls["openai"] == 0 and calls["gemini"] == 0, calls)
check("off-topic: one token + done", [n for n, _ in ev] == ["start", "token", "done"]
      and tokens_of(ev) == ["Main sirf travel mein madad karta hoon."], ev)
check("off-topic: done has the deflection + gate, saved as before",
      ev[-1][1]["reply"] == "Main sirf travel mein madad karta hoon." and ev[-1][1]["gate"] == "BLOCKED_OFF_TOPIC"
      and len(saved) == 1, ev[-1][1])
check("off-topic: log line provider=none outcome=deflected", turn_lines and "provider=none" in turn_lines[0]
      and "outcome=deflected" in turn_lines[0], turn_lines)

# ---------------------------------------------------------------- 8. TOURGUIDE_PRIMARY=gemini -> old behaviour
os.environ["TOURGUIDE_PRIMARY"] = "gemini"
reset(openai=pieces("should not run"), gemini=lambda: ("Old path answer.", False))
res, ev = stream()
check("primary=gemini: OpenAI never called", calls["openai"] == 0 and calls["gemini"] == 1, calls)
check("primary=gemini: start + done say gemini", ev[0][1] == {"provider": "gemini"} and ev[-1][1]["provider"] == "gemini")
reset(openai=pieces("should not run"), gemini=lambda: ("Old path answer.", False))
r = client.post("/api/tour-guide/chat", json={"message": "Hawa Mahal", "mode": "local"}, headers=AUTH)
check("primary=gemini: JSON route uses Gemini only", calls["openai"] == 0 and r.json().get("provider") == "gemini", r.json())
os.environ["TOURGUIDE_PRIMARY"] = "nonsense"
check("unknown TOURGUIDE_PRIMARY -> openai", tg.tourguide_primary() == "openai")
os.environ.pop("TOURGUIDE_PRIMARY", None)
check("unset TOURGUIDE_PRIMARY -> openai", tg.tourguide_primary() == "openai")

# ---------------------------------------------------------------- 9. non-streaming route: same shape + provider + grounded
OLD_KEYS = {"reply", "chips", "card", "mode", "gate", "error"}
PLACE_KEYS = {"places", "emergency", "needs_location", "place_intent"}   # added by the places feature
reset(openai=pieces("Hawa Mahal ", "dekhiye. ", '<<<CHIPS:["Timings"]>>>'))
r = client.post("/api/tour-guide/chat", json={"message": "Hawa Mahal", "mode": "local"}, headers=AUTH)
data = r.json()
check("JSON route: 200 with the old keys plus provider and grounded", r.status_code == 200
      and set(data) == OLD_KEYS | {"provider", "grounded"} | PLACE_KEYS, sorted(data))
check("JSON route: OpenAI answer, grounded false, chips parsed", data["provider"] == "openai" and data["grounded"] is False
      and data["chips"] == ["Timings"] and data["reply"] == "Hawa Mahal dekhiye.", data)
check("JSON route: saved once, log line stream=false", len(saved) == 1 and turn_lines and "stream=false" in turn_lines[0])

reset(openai=raising_before_first(), gemini=lambda: ("Grounded Gemini.", True))
data = client.post("/api/tour-guide/chat", json={"message": "Hawa Mahal", "mode": "local"}, headers=AUTH).json()
check("JSON route: OpenAI fails -> Gemini, grounded true", data["provider"] == "gemini" and data["grounded"] is True, data)

reset(openai=raising_before_first(), gemini=lambda: (None, False))
data = client.post("/api/tour-guide/chat", json={"message": "Hawa Mahal", "mode": "local"}, headers=AUTH).json()
check("JSON route: total failure keeps the old shape + error code, not saved",
      data["error"] == "LLM_TOTAL_FAILURE" and set(data) == OLD_KEYS | {"provider", "grounded"} | PLACE_KEYS
      and saved == [], data)

reset(openai=pieces("x"), guard=lambda m: (False, "BLOCKED_OFF_TOPIC", "Sirf travel."))
data = client.post("/api/tour-guide/chat", json={"message": "cricket", "mode": "local"}, headers=AUTH).json()
check("JSON route: off-topic deflection, no model call", data["reply"] == "Sirf travel." and calls["openai"] == 0, data)

reset(openai=pieces("Paas mein Apollo pharmacy hai."), guard=lambda m: (True, tg.ESSENTIAL_GATE, ""))
data = client.post("/api/tour-guide/chat", json={"message": "fever medicine", "mode": "local"}, headers=AUTH).json()
check("emergency: EMERGENCY prompt kept, OpenAI still first",
      fake.get("last_system") == tg.EMERGENCY_SYSTEM_PROMPT and data["provider"] == "openai"
      and data["chips"] == ["Locate on Map", "Quick Delivery"], data)

# ---------------------------------------------------------------- 10. auth + rate limit on the stream route
r = client.post("/api/tour-guide/chat/stream", json={"message": "Hawa Mahal"})
check("stream route needs login (401)", r.status_code == 401, r.status_code)
route = next(rt for rt in main.app.routes if getattr(rt, "path", "") == "/api/tour-guide/chat/stream")
check("stream route uses ai_chat_limiter", any(getattr(d.dependency, "key_prefix", None) == "rl:ai:chat"
                                               for d in route.dependencies), None)

# ---------------------------------------------------------------- 11. client disconnect: stop, nothing saved
async def run_disconnect():
    reset(openai=pieces("Hawa ", "Mahal ", "bahut ", "sundar ", "hai ", "aur ", "purana ", "hai.", delay=0.3))
    gone = {"v": False}

    async def is_disconnected():
        return gone["v"]

    out = []
    agen = tg.stream_concierge_events("user_x", "Hawa Mahal", recent_history=[], is_disconnected=is_disconnected)
    async for chunk in agen:
        out.append(chunk)
        if chunk.startswith("event: token"):
            gone["v"] = True
    return out


out = asyncio.run(run_disconnect())
check("disconnect: no done event", not any(c.startswith("event: done") for c in out), out)
check("disconnect: nothing saved", saved == [], saved)
time.sleep(0.8)
check("disconnect: the OpenAI worker stopped early (not all 8 pieces pulled)", fake["pulled"] < 8, fake["pulled"])
check("disconnect: log outcome=client_gone", any("outcome=client_gone" in l for l in turn_lines), turn_lines)

# ---------------------------------------------------------------- 12. prompt honesty
p = tg.JARVIS_SYSTEM_PROMPT.lower()
check("JARVIS prompt no longer promises verified real-time guidance",
      "verified, real-time" not in p and "you cannot check live information" in p)
check("JARVIS prompt still asks for CHIPS and CARD", "<<<chips:" in p and "<<<card:" in p)

# ---------------------------------------------------------------- 13. openai_client.chat_stream (fake HTTP)
class FakeStreamResp:
    def __init__(self, status, lines, body=None):
        self.status_code = status
        self._lines = lines
        self._body = body or {}
        self.headers = {}
        self.closed = False

    def iter_lines(self, decode_unicode=False):
        yield from self._lines

    def json(self):
        return self._body

    def close(self):
        self.closed = True


def sse_line(content=None, finish=None):
    delta = {"content": content} if content is not None else {}
    return b"data: " + json.dumps({"choices": [{"delta": delta, "finish_reason": finish}]}).encode()


os.environ["OPENAI_API_KEY"] = "test-key-not-real"
sent = {}
resp_holder = {}


def fake_post(url, headers=None, json=None, timeout=None, stream=False):
    sent.update(url=url, body=json, timeout=timeout, stream=stream)
    return resp_holder["r"]


openai_client.requests.post = fake_post
openai_client._NO_REASONING_EFFORT.add(openai_client.llm_model())  # skip the effort retry dance here
resp_holder["r"] = FakeStreamResp(200, [b": keepalive", sse_line("Nam"), sse_line("aste"), b"", sse_line(None, "stop"),
                                         b"data: [DONE]"])
got = list(openai_client.chat_stream([{"role": "user", "content": "hi"}], first_token_timeout=8, total_timeout=20))
check("chat_stream: yields content pieces", got == ["Nam", "aste"], got)
check("chat_stream: stream=True, 8 s read timeout, body has stream:true",
      sent["stream"] is True and sent["timeout"][1] == 8 and sent["body"]["stream"] is True, sent)
check("chat_stream: response closed", resp_holder["r"].closed)

resp_holder["r"] = FakeStreamResp(429, [], {"error": {"code": "rate_limit_exceeded"}})
try:
    list(openai_client.chat_stream([{"role": "user", "content": "hi"}]))
    ok = False
except openai_client.LLMRateLimited:
    ok = True
check("chat_stream: 429 raises LLMRateLimited before any piece", ok)

resp_holder["r"] = FakeStreamResp(200, [sse_line("Half"), sse_line(None, "length")])
seen, err = [], None
try:
    for piece in openai_client.chat_stream([{"role": "user", "content": "hi"}]):
        seen.append(piece)
except openai_client.LLMError as e:
    err = e
check("chat_stream: cut-off answer raises incomplete_length after the piece", seen == ["Half"] and err is not None
      and err.code == "incomplete_length", (seen, getattr(err, "code", None)))

resp_holder["r"] = FakeStreamResp(200, [sse_line(None, "stop")])
try:
    list(openai_client.chat_stream([{"role": "user", "content": "hi"}]))
    err = None
except openai_client.LLMError as e:
    err = e
check("chat_stream: empty answer raises empty_answer", err is not None and err.code == "empty_answer")

real_mono = openai_client.time.monotonic
clock = {"t": 0.0}


def ticking():
    clock["t"] += 15.0
    return clock["t"]


openai_client.time.monotonic = ticking
resp_holder["r"] = FakeStreamResp(200, [sse_line("a"), sse_line("b"), sse_line("c")])
try:
    list(openai_client.chat_stream([{"role": "user", "content": "hi"}], total_timeout=20))
    err = None
except openai_client.LLMError as e:
    err = e
openai_client.time.monotonic = real_mono
check("chat_stream: 20 s total limit raises total_timeout", err is not None and err.code == "total_timeout",
      getattr(err, "code", None))

# ---------------------------------------------------------------- summary
passed = sum(1 for _, ok in results if ok)
print(f"\n{passed}/{len(results)} passed")
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)
client.__exit__(None, None, None)
sys.exit(0 if passed == len(results) else 1)
