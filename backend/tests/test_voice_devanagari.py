"""
Voice yes / no / cancel in Devanagari ("हाँ।", "नहीं", "रद्द करो") as well as Roman ("haan", "nahi", "cancel").
Run from backend/: python -m tests.test_voice_devanagari
No OpenAI call, no network: the model is a fake that counts calls; the place search is a fake. Uses the local
Redis for the draft / confirm state (this test's keys are removed at the end).
"""
import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path
from unittest import mock

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"
os.environ["OPENAI_API_KEY"] = "test-key-not-real"
os.environ["VOICE_TTS_ENABLED"] = "false"
os.environ.pop("VOICE_DEBUG_STORE", None)

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

import openai_client  # noqa: E402
import places  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from trip_lifecycle import today_ist  # noqa: E402
from voice import agent, draft as D, pending as P  # noqa: E402
from tests.purpose_helper import past_purpose  # noqa: E402  (feat/trip-purpose)
from voice import text_utils as T  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if (detail != "" and not cond) else ""), flush=True)


# ---------------------------------------------------------------- normaliser
check("normalize: punctuation incl. danda -> gone, chandrabindu == anusvara", T.normalize_text("हाँ।") == T.normalize_text("हां"))
check("normalize: nukta dropped (ज़रूर == जरूर)", T.normalize_text("ज़रूर!") == "जरूर")
check("normalize: vowel signs kept (जी stays जी, not ज)", T.normalize_text("जी") == "जी" and T.words("ठीक है") == ["ठीक", "है"])
check("normalize: Latin unchanged ('Yes.' -> yes, don't -> don t)", T.words("Yes.") == ["yes"] and T.words("don't") == ["don", "t"])
check("normalize: spelling variants (नही -> नहीं, बिलकुल -> बिल्कुल)", T.words("नही बिलकुल") == ["नहीं", "बिल्कुल"])

# ---------------------------------------------------------------- yes_or_no
for t in ["हाँ।", "हां", "हाँ", "जी हाँ", "जी", "ठीक है", "हाँ कर दो", "बिल्कुल", "सही है", "ज़रूर", "हाँजी", "ओके"]:
    check(f"yes_or_no({t!r}) == yes", agent.yes_or_no(t) == "yes", agent.yes_or_no(t))
for t in ["नहीं", "नहीं नहीं", "रुको", "मत करो", "रहने दो", "रद्द करो", "कैंसल", "नही", "जी नहीं"]:
    check(f"yes_or_no({t!r}) == no", agent.yes_or_no(t) == "no", agent.yes_or_no(t))
for t, want in [("haan", "yes"), ("yes", "yes"), ("ok", "yes"), ("Yes.", "yes"), ("haan sahi hai", "yes"),
                ("nahi", "no"), ("no", "no"), ("cancel", "no"), ("cancel karo", "no"),
                ("ji", None), ("galat", None)]:
    check(f"Roman unchanged: yes_or_no({t!r}) == {want}", agent.yes_or_no(t) == want, agent.yes_or_no(t))
for t in ["बजट पंद्रह हजार", "गोवा जाना है", "हाँ हाँ हाँ हाँ हाँ हाँ", "haan haan haan haan haan haan", ""]:
    check(f"not a yes/no: {t!r}", agent.yes_or_no(t) is None, agent.yes_or_no(t))

# ---------------------------------------------------------------- is_garbled
for t, want in [("हाँ।", False), ("जी", False), ("ना", False), ("a", True), ("...", True), ("50000", False), ("", True),
                ("।", True), ("ok", False), ("५००००", False)]:
    check(f"is_garbled({t!r}) == {want}", agent.is_garbled(t) is want, agent.is_garbled(t))

# ---------------------------------------------------------------- end to end through run_agent
TODAY = today_ist()
d = lambda n: (TODAY + timedelta(days=n)).isoformat()  # noqa: E731
USER = f"usr_dev_{uuid.uuid4().hex[:6]}"
PLACES = {"goa": [{"id": "ChIJgoa", "place_id": "ChIJgoa", "name": "Goa", "latitude": 15.29, "longitude": 74.12, "city": "Goa, India"}]}


class FakeTools:
    queue, calls = [], 0

    def __call__(self, messages, tools, **kw):
        FakeTools.calls += 1
        kind, payload = FakeTools.queue.pop(0)
        return {"content": None, "tool_calls": [{"name": payload[0], "arguments": payload[1]}]}


def ra(text, conv, queue=None):
    if queue is not None:
        FakeTools.queue = list(queue)
    r = agent.run_agent(text, "hi", user_id=USER, conversation_id=conv, screen="/home", trip=None, redis_conn=redis_conn)
    return past_purpose(r, conv, lambda: D.load(redis_conn, USER, conv), lambda t: agent.run_agent(
        t, "hi", user_id=USER, conversation_id=conv, screen="/home", trip=None, redis_conn=redis_conn))


FULL_DRAFT = [("tool", ("update_trip_draft", {"destination": "Goa", "start_date": d(20), "end_date": d(23),
                                              "adults": 2, "children": 0, "budget_inr": 50000}))]


def summary(r):
    return (r.action, r.step, r.error_code, [a.get("type") for a in (r.ui_actions or [])], bool(r.pending_confirmation))


with mock.patch.object(openai_client, "chat_tools", FakeTools()), \
        mock.patch.object(places, "search_places", lambda q: PLACES.get(q.strip().lower(), [])):
    outcomes = {}
    for said in ("haan", "हाँ।"):
        conv = f"conv_dev_{uuid.uuid4().hex[:6]}"
        ra("Goa jaana hai", conv, queue=FULL_DRAFT)
        r0 = ra("पता नहीं", conv)                   # "Kahan se jaana hai?" (optional origin) -> skipped, no LLM call
        calls_before = FakeTools.calls
        r1 = ra(said, conv)                         # answer to the date read-back
        no_llm_1 = FakeTools.calls == calls_before
        r2 = ra(said, conv)                         # answer to the Confirm card
        no_llm_2 = FakeTools.calls == calls_before
        outcomes[said] = (r0.step, summary(r1), summary(r2), no_llm_1 and no_llm_2,
                          D.load(redis_conn, USER, conv) is None and P.get(redis_conn, USER, conv) is None)
    h, dv = outcomes["haan"], outcomes["हाँ।"]
    check("read-back asked first (draft awaiting the date)", h[0] == "confirm_date" and dv[0] == "confirm_date", (h[0], dv[0]))
    check("'हाँ।' to the date read-back == 'haan' (ready + Confirm card)", dv[1] == h[1] and h[1][1] == "ready", (dv[1], h[1]))
    check("'हाँ।' to the Confirm card == 'haan' (same confirm action)", dv[2] == h[2], (dv[2], h[2]))
    check("'हाँ।': no LLM call, no no_words error", dv[3] and dv[1][2] is None and dv[2][2] is None, dv)
    check("'हाँ।': draft and pending cleared like 'haan'", dv[4] == h[4] and dv[4])

    conv = f"conv_dev_{uuid.uuid4().hex[:6]}"
    ra("Goa jaana hai", conv, queue=FULL_DRAFT)
    ra("पता नहीं", conv)
    r = ra("नहीं", conv)
    check("'नहीं' to the date read-back -> dates cleared, asked again (like 'nahi')",
          r.reply_text == agent.DATE_AGAIN["hi"] and D.load(redis_conn, USER, conv).start_date is None, r.reply_text)

    conv = f"conv_dev_{uuid.uuid4().hex[:6]}"
    ra("Goa jaana hai", conv, queue=FULL_DRAFT)
    ra("पता नहीं", conv)
    ra("हाँ", conv)
    r = ra("नहीं", conv)
    check("'नहीं' on the Confirm card -> cancelled (like 'nahi')", r.action == "trip_cancel" and P.get(redis_conn, USER, conv) is None,
          r.action)

    for words_said in ("रद्द करो", "कैंसल", "cancel karo"):
        conv = f"conv_dev_{uuid.uuid4().hex[:6]}"
        ra("Goa jaana hai", conv, queue=[("tool", ("update_trip_draft", {"destination": "Goa"}))])
        calls_before = FakeTools.calls
        r = ra(words_said, conv)
        check(f"{words_said!r} cancels a draft trip (no LLM call)", r.action == "trip_cancel" and D.load(redis_conn, USER, conv) is None
              and FakeTools.calls == calls_before, (r.action, r.reply_text))

    conv = f"conv_dev_{uuid.uuid4().hex[:6]}"
    calls_before = FakeTools.calls
    r = ra("।", conv)
    check("a lone danda is still noise: unclear, no_words, no LLM call",
          r.error_code == "no_words" and FakeTools.calls == calls_before, r.error_code)

for prefix in ("voice:mem", "voice:pending", "voice:draft", "voice:confirm"):
    for key in redis_conn.scan_iter(f"{prefix}:{USER}:*"):
        redis_conn.delete(key)
print(f"\n{sum(results)}/{len(results)} passed", flush=True)
sys.exit(0 if all(results) else 1)
