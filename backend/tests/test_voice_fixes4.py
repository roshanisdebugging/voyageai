"""
"Fixes before Step 4" checks (voicefirst.md): where-is vs show, haan/yes pending map, weather tool,
garbled vs off-topic, transient-error retry, reply language from text, note never spoken,
real total time and accurate agent_action. LLMs, Google search and Open-Meteo simulated; TTS simulated.
Run from backend/: python -m tests.test_voice_fixes4
"""
import io
import json
import logging
import math
import os
import struct
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
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
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'voice_f4.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
import openai_client  # noqa: E402
import places  # noqa: E402
import weather_service  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from models_trip import TripModel  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from trip_lifecycle import today_ist  # noqa: E402
from voice import agent, lang, pipeline  # noqa: E402
from voice.stt import STTResult  # noqa: E402
from voice.tools import lookups  # noqa: E402

main.SessionLocal = database.SessionLocal
database.Base.metadata.create_all(bind=database.engine)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


USER = f"usr_f4_{uuid.uuid4().hex[:8]}"
TODAY = today_ist()
TAJ = [{"id": "ChIJtaj", "place_id": "ChIJtaj", "name": "Taj Mahal", "country": "India", "latitude": 27.1751, "longitude": 78.0421,
        "city": "Dharmapuri, Forest Colony, Tajganj, Agra, Uttar Pradesh, India"}]
HAWA = [{"id": "ChIJhawa", "place_id": "ChIJhawa", "name": "Hawa Mahal", "country": "India", "latitude": 26.9240, "longitude": 75.8267,
         "city": "Hawa Mahal Road, Badi Choupad, Pink City, Jaipur, Rajasthan, India"}]
JAIPUR = [{"id": "ChIJjaipur", "place_id": "ChIJjaipur", "name": "Jaipur", "country": "India", "latitude": 26.91, "longitude": 75.79,
           "city": "Rajasthan, India"}]


class FakeTools:
    queue, calls = [], []

    def __call__(self, messages, tools, **kw):
        FakeTools.calls.append(messages)
        item = FakeTools.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        kind, payload = item
        if kind == "tool":
            return {"content": None, "tool_calls": [{"name": payload[0], "arguments": payload[1]}]}
        return {"content": payload, "tool_calls": []}


fake = FakeTools()


def conv():
    return f"conv_f4_{uuid.uuid4().hex[:6]}"


def ra(text, c=None, stt_lang="hi", trip=None):
    return agent.run_agent(text, stt_lang, user_id=USER, conversation_id=c or conv(), screen="/home", trip=trip, redis_conn=redis_conn)


# ---------------- item 8: language from the words
for text, want in [("Taj Mahal kahan hai", "hi"), ("map kholo", "hi"), ("where is Taj Mahal", "en"), ("show me Hawa Mahal", "en"),
                   ("ek joke sunao", "hi"), ("कल मौसम कैसा है", "hi"), ("my trip please", "en"), ("Goa trip kholo", "hi"),
                   ("Taj Mahal Agra, Uttar Pradesh mein hai. Map par dikhaun?", "hi"), ("Showing Hawa Mahal on the map.", "en")]:
    check(f"detect_lang({text!r}) = {want}", lang.detect_lang(text) == want, lang.detect_lang(text))
check("no words -> Whisper's tag decides", lang.detect_lang("...", "en") == "en" and lang.detect_lang("", "hi") == "hi")
check("sarvam code from text", lang.sarvam_code("Kal Jaipur mein baarish ka 20% chance hai.") == "hi-IN"
      and lang.sarvam_code("Tomorrow in Jaipur: 20% chance of rain.") == "en-IN")

with mock.patch.object(openai_client, "chat_tools", fake):
    # ---------------- item 3: where is vs show me
    with mock.patch.object(places, "search_places", lambda q: TAJ):
        c = conv()
        FakeTools.queue = [("tool", ("search_places", {"query": "Taj Mahal", "show": False}))]
        r = ra("Taj Mahal kahan hai", c)
        check("'kahan hai' -> answers city/state and asks; no map yet",
              r.reply_text == "Taj Mahal Agra, Uttar Pradesh mein hai. Map par dikhaun?" and r.ui_actions == [] and r.action == "where", r.reply_text)
        n = len(FakeTools.calls)
        r = ra("haan", c)
        check("'haan' -> the kept map actions run, no OpenAI call",
              r.ui_actions and r.ui_actions[0]["type"] == "map_focus" and r.ui_actions[0]["name"] == "Taj Mahal"
              and r.ui_actions[1] == {"type": "navigate", "to": "/map"} and r.action == "map_focus" and len(FakeTools.calls) == n, r)
        r2_conv = conv()
        FakeTools.queue = [("tool", ("search_places", {"query": "Taj Mahal", "show": False}))]
        r = ra("where is Taj Mahal", r2_conv, stt_lang="hi")
        check("English question -> English answer", r.reply_text == "Taj Mahal is in Agra, Uttar Pradesh. Shall I show it on the map?", r.reply_text)
        r = ra("no thanks", r2_conv)
        check("'no thanks' -> nothing opens", r.ui_actions == [] and r.reply_text == "Okay.", r.reply_text)
        FakeTools.queue = [("text", "Kya dikhaun?")]
        r = ra("haan", r2_conv)
        check("pending is used once only", not any(a.get("type") == "map_focus" for a in r.ui_actions))
    c = conv()
    with mock.patch.object(places, "search_places", lambda q: TAJ):
        FakeTools.queue = [("tool", ("search_places", {"query": "Taj Mahal", "show": False})),
                           ("tool", ("navigate", {"page": "food"}))]
        ra("Taj Mahal kahan hai", c)
        r = ra("food page kholo", c)
    check("another request after the question -> the pending map is dropped", r.ui_actions == [{"type": "navigate", "to": "/food"}])
    with mock.patch.object(places, "search_places", lambda q: HAWA):
        FakeTools.queue = [("tool", ("search_places", {"query": "Hawa Mahal", "show": True}))]
        r = ra("Hawa Mahal dikhao")
    check("'dikhao' -> map at once, reply names the city", r.reply_text == "Hawa Mahal, Jaipur: map par dikha diya." and r.action == "map_focus"
          and r.ui_actions[0]["type"] == "map_focus", r.reply_text)
    check("search tool has show (required)", agent.SEARCH_TOOL["function"]["parameters"]["required"] == ["query", "show"])

    # ---------------- item 4: weather
    fc_calls = []

    def fake_fc(lat, lng, s, e):
        fc_calls.append((round(lat, 2), round(lng, 2), s, e))
        return {"source": "open-meteo", "days": [{"date": s, "condition": "Light rain", "badWeather": False, "tempMaxC": 24.4,
                                                    "tempMinC": 15.0, "rainChancePercent": 20}]}
    with mock.patch.object(places, "search_places", lambda q: JAIPUR), mock.patch.object(weather_service, "get_trip_forecast", fake_fc):
        FakeTools.queue = [("tool", ("get_weather", {"place": "Jaipur", "day": "tomorrow"}))]
        r = ra("kal Jaipur mein baarish hogi kya")
        check("weather: real forecast reply", r.reply_text == "Kal Jaipur mein baarish ka 20% chance hai, high 24°C." and r.action == "weather", r.reply_text)
        check("weather: asked Open-Meteo for tomorrow at the place", fc_calls[-1] == (26.91, 75.79, (TODAY + timedelta(days=1)).isoformat(),
                                                                                        (TODAY + timedelta(days=1)).isoformat()), fc_calls[-1:])
        FakeTools.queue = [("tool", ("get_weather", {"place": "Jaipur", "day": None}))]
        r = ra("what's the weather in Jaipur", stt_lang="en")
        check("weather: English, today", r.reply_text == "Today in Jaipur: 20% chance of rain, high 24°C.", r.reply_text)
        FakeTools.queue = [("tool", ("get_weather", {"place": "Jaipur", "day": (TODAY + timedelta(days=30)).isoformat()}))]
        r = ra("next month Jaipur weather", stt_lang="en")
        check("weather: too far ahead -> says so, no call", r.error_code == "too_far" and len(fc_calls) == 2)
        FakeTools.queue = [("tool", ("get_weather", {"place": None, "day": "today"}))]
        r = ra("aaj mausam kaisa hai")
        check("weather without place or trip -> asks which place", r.reply_text == "Kis jagah ka mausam batau?", r.reply_text)
    with mock.patch.object(weather_service, "get_trip_forecast", lambda *a: (_ for _ in ()).throw(weather_service.ForecastUnavailable("x"))), \
            mock.patch.object(places, "search_places", lambda q: JAIPUR):
        FakeTools.queue = [("tool", ("get_weather", {"place": "Jaipur", "day": "today"}))]
        r = ra("aaj Jaipur ka mausam")
        check("weather unavailable -> says so, never invents", r.reply_text == "Abhi mausam ki jaankari nahi mil rahi." and r.error_code == "unavailable")
    # the open trip's destination, checked against the session user
    tid = f"trip_{uuid.uuid4().hex[:8]}"
    other = f"trip_{uuid.uuid4().hex[:8]}"
    with database.SessionLocal() as db:
        for t_id, uid in ((tid, USER), (other, "usr_someone_else")):
            db.add(TripModel(id=t_id, user_id=uid, title="Udaipur Trip", status="PLANNING", start_date=TODAY.isoformat(),
                             end_date=(TODAY + timedelta(days=2)).isoformat(), total_days=3,
                             destination_json=json.dumps({"name": "Udaipur", "latitude": 24.58, "longitude": 73.71}),
                             travelers_json="[]", created_at="x", updated_at="x"))
        db.commit()
    with mock.patch.object(weather_service, "get_trip_forecast", fake_fc):
        FakeTools.queue = [("tool", ("get_weather", {"day": "tomorrow"}))]
        r = ra("kal mausam kaisa rahega", trip=agent.TripInfo("Udaipur Trip", None, None, id=tid))
        check("weather without a place -> the open trip's destination", r.reply_text.startswith("Kal Udaipur mein") and fc_calls[-1][:2] == (24.58, 73.71), r.reply_text)
        FakeTools.queue = [("tool", ("get_weather", {"day": "tomorrow"}))]
        r = ra("kal mausam kaisa rahega", trip=agent.TripInfo("x", None, None, id=other))
        check("someone else's trip id -> not used", r.reply_text == "Kis jagah ka mausam batau?", r.reply_text)
    check("prompt sends weather to get_weather, never answer_question", "Never use answer_question for weather" in agent.build_system_prompt(None, None))

    # ---------------- item 6: garbled vs off-topic
    n = len(FakeTools.calls)
    r = ra(".. ?")
    check("no words -> 'Samajh nahi aaya', no LLM call", r.reply_text == "Samajh nahi aaya, phir se boliye." and r.action == "unclear" and len(FakeTools.calls) == n)
    FakeTools.queue = [("tool", ("cant_help", {"reason": "unclear"}))]
    r = ra("blorf manta kizzle")
    check("garbled words -> cant_help(unclear) -> 'Samajh nahi aaya, phir se boliye.'", r.reply_text == "Samajh nahi aaya, phir se boliye."
          and r.action == "unclear", (r.reply_text, r.action))
    FakeTools.queue = [("tool", ("cant_help", {"reason": "off_topic"}))]
    r = ra("ek joke sunao")
    check("off-topic -> decline line, action decline", r.reply_text == "Main sirf aapki trip mein madad kar sakta hoon." and r.action == "decline")
    FakeTools.queue = [("tool", ("cant_help", {"reason": "off_topic"}))]
    r = ra("who won the cricket match", stt_lang="hi")
    check("English off-topic -> English decline", r.reply_text == "I can only help with your trip.", r.reply_text)

    # ---------------- item 7: retry once on transient OpenAI errors
    FakeTools.queue = [openai_client.LLMTransient("OpenAI HTTP 500"), ("tool", ("navigate", {"page": "map"}))]
    r = ra("map kholo")
    check("transient error once -> retried -> works", r.ui_actions == [{"type": "navigate", "to": "/map"}], r)
    FakeTools.queue = [openai_client.LLMTransient("x"), openai_client.LLMTransient("x")]
    r = ra("map kholo")
    check("twice -> fallback reply", r.reply_text == agent.FALLBACK_REPLY and r.error_code == "llm_transient_twice")
    FakeTools.queue = [openai_client.LLMRateLimited("x")]
    r = ra("map kholo")
    check("rate limit -> no retry, fallback", r.error_code == "rate_limited" and not FakeTools.queue)

# openai_client: 5xx -> LLMTransient (status and error code only, never the message)
class R:
    def __init__(self, code, body):
        self.status_code, self._b, self.text = code, body, "body with the user's words"
    def json(self):
        return self._b
with mock.patch.object(openai_client.requests, "post", lambda *a, **k: R(503, {"error": {"code": "server_error", "message": "user words here"}})):
    try:
        openai_client.chat_tools([{"role": "user", "content": "x"}], agent.TOOLS)
        check("5xx -> LLMTransient", False)
    except openai_client.LLMTransient as e:
        check("5xx -> LLMTransient, message has the status and code only", "503" in str(e) and "server_error" in str(e) and "user words" not in str(e), str(e))
with mock.patch.object(openai_client.requests, "post", lambda *a, **k: R(400, {"error": {"code": "invalid_request_error"}})):
    try:
        openai_client.chat_tools([{"role": "user", "content": "x"}], agent.TOOLS)
    except openai_client.LLMTransient:
        check("other 400 is not retried", False)
    except openai_client.LLMError:
        check("other 400 is not retried", True)
check("tool schemas: optional args accept null", agent.WEATHER_TOOL["function"]["parameters"]["properties"]["place"]["type"] == ["string", "null"]
      and agent.ANSWER_TOOL["function"]["parameters"]["properties"]["facts"]["type"] == ["boolean", "null"])

# ---------------- items 5, 8, 9 through the socket: note not spoken, TTS language from text, real total time
client = TestClient(main.app)
client.__enter__()
r = client.post("/api/auth/register", json={"name": "Voice Four", "email": "voicef4@example.com", "password": "secret123"})
TOK = r.json()["token"]
client.cookies.clear()


def pcm(seconds):
    n_ = int(16000 * seconds)
    return b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 16000))) for i in range(n_))


class FakeSTT:
    text, language = "Amber Fort kab jaana best hai", "en"   # Whisper tags Hinglish as "en"

    def transcribe(self, audio):
        return STTResult(text=FakeSTT.text, language=FakeSTT.language, duration_ms=1000, latency_ms=50, provider="openai", model="w")


def recv_until(ws, kinds):
    while True:
        m_ = ws.receive_json()
        if m_.get("type") in kinds:
            return m_


tts_calls, saved_turns = [], []


def fake_tts(text, language):
    tts_calls.append((text, language))
    time.sleep(0.25)  # TTS takes time: total_time must include it
    return None, "audio/wav", 250, "tts_disabled"


def fake_agent(text, stt_language, **kw):
    time.sleep(0.2)
    return agent.AgentResult("Amber Fort subah jaana accha hai. Dopahar mein garmi hoti hai.", action="answer", llm_ms=120, tool_ms=80,
                             note="Details badal sakti hain.")


buf = io.StringIO()
logging.getLogger("voice").addHandler(logging.StreamHandler(buf))
with mock.patch.object(pipeline, "get_stt", lambda: FakeSTT()), mock.patch.object(pipeline, "synthesize_reply", fake_tts), \
        mock.patch.object(pipeline, "run_agent", fake_agent), \
        mock.patch.object(pipeline.debug_store, "enabled", lambda: True), \
        mock.patch.object(pipeline.debug_store, "end_session", lambda *a, **k: None), \
        mock.patch.object(pipeline.debug_store, "save_speech", lambda pcm_, ctx, res, total: saved_turns.append((res.action, total, res.stt_ms))):
    with client.websocket_connect("/ws/voice", headers={"origin": "http://localhost:5173"}) as ws:
        ws.send_json({"type": "auth", "token": TOK})
        recv_until(ws, {"ready"})
        ws.send_json({"type": "start", "conversation_id": "conv_f4_ws", "screen": "/home"})
        recv_until(ws, {"recording"})
        ws.send_bytes(pcm(1.0))
        ws.send_json({"type": "stop"})
        recv_until(ws, {"transcript"})
        rep = recv_until(ws, {"reply"})
        deadline = time.time() + 5
        while not saved_turns and time.time() < deadline:
            time.sleep(0.05)
check("reply: note sent as its own field", rep.get("note") == "Details badal sakti hain." and "Details" not in rep["reply_text"], rep)
check("TTS speaks the reply only (not the note)", tts_calls and "Details" not in tts_calls[-1][0])
check("TTS language from the reply text (Hinglish -> hi) even though Whisper said 'en'", tts_calls and tts_calls[-1][1] == "hi", tts_calls)
check("test-only store: total time = stop -> reply (includes agent + TTS), not the STT time",
      saved_turns and saved_turns[-1][1] >= 450 and saved_turns[-1][1] > saved_turns[-1][2], saved_turns)
check("test-only store: agent_action as decided", saved_turns and saved_turns[-1][0] == "answer")
check("log has total_ms per turn, no words", "total_ms=" in buf.getvalue() and "Amber" not in buf.getvalue())
client.__exit__(None, None, None)

for key in list(redis_conn.scan_iter(f"voice:*:{USER}:*")):
    redis_conn.delete(key)
print(f"\n{sum(results)}/{len(results)} passed", flush=True)
sys.exit(0 if all(results) else 1)
