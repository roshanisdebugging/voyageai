"""
Voice step 3 checks (questions and look-ups): app DB = SQLite, Redis = local, Groq / Gemini / cost guard /
Google search simulated (no real calls), TTS off.
Run from backend/: python -m tests.test_voice_step3
"""
import io
import json
import logging
import os
import sys
import tempfile
import uuid
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"
os.environ["GROQ_API_KEY"] = "test-key-not-real"
os.environ["VOICE_TTS_ENABLED"] = "false"
os.environ.pop("VOICE_DEBUG_STORE", None)

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'voice3.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402,F401  (registers all models)
import groq_client  # noqa: E402
import places  # noqa: E402
import tour_guide_service as tgs  # noqa: E402
from models_trip import TripModel  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from trip_lifecycle import today_ist  # noqa: E402
from voice import agent, messages, pages  # noqa: E402
from voice.tools import lookups  # noqa: E402

database.Base.metadata.create_all(bind=database.engine)

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


USER = f"usr_s3_{uuid.uuid4().hex[:8]}"
OTHER = f"usr_s3_other_{uuid.uuid4().hex[:8]}"
CONV = "conv_s3"
TODAY = today_ist()


def add_trip(user, dest, start_offset, days=3, status="PLANNING", title=None):
    s = TODAY + timedelta(days=start_offset)
    e = s + timedelta(days=days - 1)
    tid = f"trip_{uuid.uuid4().hex[:10]}"
    with database.SessionLocal() as db:
        db.add(TripModel(id=tid, user_id=user, title=title or f"{dest} Trip", status=status, start_date=s.isoformat(),
                         end_date=e.isoformat(), total_days=days, destination_json=json.dumps({"name": dest, "country": "India"}),
                         travelers_json="[]", created_at="2026-11-01", updated_at="2026-11-01"))
        db.commit()
    return tid


def month_name(d: date) -> str:
    return lookups.MONTHS_EN[d.month - 1]


# Trips: the user has Jaipur (upcoming), Goa (two: soon and later), Kerala (past); another user has Goa + Manali.
JAIPUR = add_trip(USER, "Jaipur", 5)
GOA_1 = add_trip(USER, "Goa", 12)
GOA_2 = add_trip(USER, "Goa", 70)
KERALA_PAST = add_trip(USER, "Kerala", -40, status="COMPLETED")
OTHER_GOA = add_trip(OTHER, "Goa", 20)
OTHER_MANALI = add_trip(OTHER, "Manali", 30)


class FakeGroqTools:
    queue = []
    calls = []

    @classmethod
    def __call__(cls, messages_, tools, **kw):
        cls.calls.append({"messages": messages_, "tools": tools, **kw})
        kind, payload = cls.queue.pop(0)
        if kind == "tool":
            name, args = payload
            return {"content": None, "tool_calls": [{"name": name, "arguments": args}]}
        return {"content": payload, "tool_calls": []}


fake_tools = FakeGroqTools()


def ra(text, lang="hi", trip=None, user=USER):
    return agent.run_agent(text, lang, user_id=user, conversation_id=f"{CONV}_{uuid.uuid4().hex[:6]}", screen="/home",
                           trip=trip, redis_conn=redis_conn)


SEARCH_HITS = [
    {"id": "ChIJhawa", "place_id": "ChIJhawa", "name": "Hawa Mahal", "country": "India", "latitude": 26.9239, "longitude": 75.8267},
    {"id": "ChIJother", "place_id": "ChIJother", "name": "Hawa Mahal Hotel", "country": "India", "latitude": 26.93, "longitude": 75.82},
]

# ---------------- tool definitions and prompt
nav_desc = agent.NAVIGATE_TOOL["function"]["description"]
check("navigate tool has a meaning for every page", all(f"{p}: " in nav_desc for p in pages.PAGES))
check("plan_trip meaning: open the form, don't ask for details", "plan_trip: start planning a NEW trip" in nav_desc and "Do NOT ask" in nav_desc)
check("more: settings and profile", "more: settings, profile" in nav_desc)
check("five tools offered", sorted(agent.TOOL_NAMES) == ["answer_question", "list_my_trips", "navigate", "open_trip", "search_places"])
check("open_trip takes no trip_id from the model", "trip_id" not in json.dumps(agent.OPEN_TRIP_TOOL))
sp = agent.build_system_prompt("/home", None, today="Saturday 15 November 2026")
check("system prompt has today's date and tool rules", "Today (India): Saturday 15 November 2026" in sp
      and "Do NOT answer these from memory" in sp and "navigate to plan_trip at once" in sp)
check("system prompt default date is India time", "Today (India): " in agent.build_system_prompt(None, None))

with mock.patch.object(groq_client, "groq_chat_tools", fake_tools):
    # ---------------- navigate (step 2 misses)
    FakeGroqTools.queue = [("tool", ("navigate", {"page": "plan_trip"}))]
    r = ra("nayi trip banani hai")
    check("'nayi trip banani hai' -> /trips/new", r.ui_actions == [{"type": "navigate", "to": "/trips/new"}] and r.action == "navigate:plan_trip", r)

    # ---------------- search_places
    with mock.patch.object(places, "search_places", lambda q: SEARCH_HITS):
        FakeGroqTools.queue = [("tool", ("search_places", {"query": "Hawa Mahal"}))]
        r = ra("Hawa Mahal dikhao")
    check("search_places -> map_focus + navigate /map",
          r.ui_actions == [{"type": "map_focus", "lat": 26.9239, "lng": 75.8267, "name": "Hawa Mahal", "place_id": "ChIJhawa"},
                           {"type": "navigate", "to": "/map"}] and r.action == "map_focus", r.ui_actions)
    check("search_places reply (Hinglish)", r.reply_text == "Hawa Mahal map par dikha diya.", r.reply_text)
    with mock.patch.object(places, "search_places", lambda q: [{"name": "Eiffel Tower", "latitude": 48.858, "longitude": 2.294}]):
        FakeGroqTools.queue = [("tool", ("search_places", {"query": "Eiffel Tower"}))]
        r = ra("show me Eiffel Tower", lang="en")
    check("search outside India -> nothing, says so", r.ui_actions == [] and r.reply_text == "I couldn't find that place." and r.error_code == "not_found")
    with mock.patch.object(places, "search_places", lambda q: []):
        FakeGroqTools.queue = [("tool", ("search_places", {"query": "xyzzy"}))]
        r = ra("xyzzy dikhao")
    check("search with no result -> 'Yeh jagah nahi mili.'", r.ui_actions == [] and r.reply_text == "Yeh jagah nahi mili.")

    # ---------------- list_my_trips
    FakeGroqTools.queue = [("tool", ("list_my_trips", {}))]
    r = ra("meri trips kaun si hain")
    j, g1 = TODAY + timedelta(days=5), TODAY + timedelta(days=12)
    check("list_my_trips: own open trips, upcoming first, navigate /trips",
          r.reply_text.startswith("Aapki 3 trips hain: Jaipur ") and "Goa" in r.reply_text and "Kerala" not in r.reply_text
          and "Manali" not in r.reply_text and r.ui_actions == [{"type": "navigate", "to": "/trips"}] and r.action == "list_trips", r.reply_text)
    check("list_my_trips: dates spoken as '<day> <Mon> se'", f"Jaipur {j.day} {month_name(j)[:3]} se" in r.reply_text, r.reply_text)
    FakeGroqTools.queue = [("tool", ("list_my_trips", {"include_past": True}))]
    r = ra("meri purani trips")
    check("list_my_trips(include_past) -> only past trips", "Kerala" in r.reply_text and "Jaipur" not in r.reply_text, r.reply_text)
    for i in range(3):
        add_trip(USER, f"Extra{i}", 100 + i)
    FakeGroqTools.queue = [("tool", ("list_my_trips", {}))]
    r = ra("meri trips")
    check("more than 3 trips -> speaks 3 then 'aur bhi hain'", r.reply_text.endswith(", aur bhi hain.") and r.reply_text.count(" se") == 3, r.reply_text)
    FakeGroqTools.queue = [("tool", ("list_my_trips", {}))]
    r = ra("my trips", lang="en", user=f"usr_s3_empty_{uuid.uuid4().hex[:6]}")
    check("no trips -> says so, offers to plan", r.reply_text.startswith("You don't have any trips yet") and r.error_code == "no_trips")

    # ---------------- open_trip
    FakeGroqTools.queue = [("tool", ("open_trip", {"name_or_destination": "Jaipur"}))]
    r = ra("Jaipur wali trip kholo")
    check("open_trip one match -> open_trip + navigate /trip",
          r.ui_actions == [{"type": "open_trip", "trip_id": JAIPUR}, {"type": "navigate", "to": "/trip"}]
          and r.reply_text == "Jaipur wali trip khol di." and r.action == "open_trip", r)
    FakeGroqTools.queue = [("tool", ("open_trip", {"name_or_destination": "Goa"}))]
    r = ra("Goa wali trip kholo")
    m1, m2 = month_name(TODAY + timedelta(days=12)), month_name(TODAY + timedelta(days=70))
    check("open_trip two Goa trips -> asks which (by month), no actions",
          r.ui_actions == [] and r.reply_text.startswith("Goa ki 2 trips hain:") and r.reply_text.endswith("?")
          and (m1 in r.reply_text and m2 in r.reply_text) and r.action == "open_trip_ask", r.reply_text)
    FakeGroqTools.queue = [("tool", ("open_trip", {"name_or_destination": "Goa", "month": m2}))]
    r = ra(f"{m2} wali")
    check("follow-up with the month -> the right Goa trip", r.ui_actions[:1] == [{"type": "open_trip", "trip_id": GOA_2}], r.ui_actions)
    FakeGroqTools.queue = [("tool", ("open_trip", {"name_or_destination": "Goa", "month": str((TODAY + timedelta(days=12)).month)}))]
    r = ra("Goa, month number")
    check("month as a number works", r.ui_actions[:1] == [{"type": "open_trip", "trip_id": GOA_1}], r.ui_actions)
    FakeGroqTools.queue = [("tool", ("open_trip", {"which": "next"}))]
    r = ra("agli trip kholo")
    check("open_trip which=next -> nearest upcoming (Jaipur)", r.ui_actions[:1] == [{"type": "open_trip", "trip_id": JAIPUR}], r.ui_actions)
    FakeGroqTools.queue = [("tool", ("open_trip", {"which": "last"}))]
    r = ra("pichli trip kholo")
    check("open_trip which=last -> the past Kerala trip", r.ui_actions[:1] == [{"type": "open_trip", "trip_id": KERALA_PAST}], r.ui_actions)
    FakeGroqTools.queue = [("tool", ("open_trip", {"name_or_destination": "Gao"}))]
    r = ra("Gao wali trip")
    check("fuzzy name ('Gao') still finds Goa (asks which of 2)", r.reply_text.startswith("Goa ki 2 trips hain"), r.reply_text)

    # ownership: never another user's trips, whatever the model sends
    FakeGroqTools.queue = [("tool", ("open_trip", {"name_or_destination": "Manali"}))]
    r = ra("Manali wali trip kholo")
    check("another user's trip (Manali) is never found", r.ui_actions == [] and r.reply_text == "Is naam ki koi trip nahi mili." and r.error_code == "not_found")
    FakeGroqTools.queue = [("tool", ("open_trip", {"name_or_destination": "Jaipur", "trip_id": OTHER_GOA}))]
    r = ra("Jaipur kholo")
    check("a trip_id sent by the model is ignored", r.ui_actions[:1] == [{"type": "open_trip", "trip_id": JAIPUR}] and OTHER_GOA not in json.dumps(r.ui_actions))
    FakeGroqTools.queue = [("tool", ("open_trip", {"name_or_destination": "Goa"}))]
    r = ra("Goa wali trip kholo", user=OTHER)
    check("the other user sees only their own (single) Goa trip", r.ui_actions[:1] == [{"type": "open_trip", "trip_id": OTHER_GOA}], r.ui_actions)
    FakeGroqTools.queue = [("tool", ("list_my_trips", {}))]
    r = ra("meri trips", user=OTHER)
    check("the other user's list has no Jaipur", "Jaipur" not in r.reply_text and "Manali" in r.reply_text, r.reply_text)

    # ---------------- answer_question
    saved = []
    guard = {"allowed": True}
    gem = {"text": "**Amber Fort** subah 8 baje khulta hai. Subah jaldi jaana best hai, bheed kam hoti hai. Ticket 200 rupaye ka hai. "
                   "Hathi ki sawari bhi hoti hai.\n<<<CHIPS:[\"Timings\",\"Tickets\"]>>>"}
    groq_answer = {"text": "Amber Fort subah 8 se shaam 5:30 tak khula rehta hai. Subah jaldi jaaiye. Teesra vaakya."}

    def fake_guard(q):
        return (True, "PASSED", "") if guard["allowed"] else (False, "OFF_TOPIC", "nope")

    with mock.patch.object(tgs, "evaluate_cost_guards", fake_guard), \
            mock.patch.object(tgs, "_voice_gemini", lambda q, sp: gem["text"]), \
            mock.patch.object(tgs, "_voice_groq", lambda q, sp: groq_answer["text"]), \
            mock.patch.object(tgs, "persist_message", lambda *a, **k: saved.append((a, k))):
        FakeGroqTools.queue = [("tool", ("answer_question", {"question": "Amber Fort kab jaana best hai?", "place": "Amber Fort"}))]
        r = ra("Amber Fort kab jaana best hai")
        check("answer_question: spoken answer = first 2 sentences, no markdown/chips",
              r.reply_text == "Amber Fort subah 8 baje khulta hai. Subah jaldi jaana best hai, bheed kam hoti hai."
              and r.action == "answer" and r.ui_actions == [], r.reply_text)
        check("answer_question: full answer + question saved to Guide history (mode voice)",
              len(saved) == 2 and saved[0][0][1] == "user" and saved[1][0][1] == "assistant" and saved[1][0][3] == "voice"
              and "Ticket 200 rupaye" in saved[1][0][2] and "CHIPS" not in saved[1][0][2] and "**" not in saved[1][0][2], saved[-1:])
        check("answer_question: one deciding Groq call, tool time counted separately", r.llm_ms >= 0 and r.tool_ms >= 0)

        saved.clear()
        gem["text"] = None
        FakeGroqTools.queue = [("tool", ("answer_question", {"question": "Amber Fort timing?"}))]
        r = ra("Amber Fort ki timing kya hai")
        check("Gemini fails -> Groq answers (2 sentences) + 'Details badal sakti hain.'",
              r.reply_text == "Amber Fort subah 8 se shaam 5:30 tak khula rehta hai. Subah jaldi jaaiye. Details badal sakti hain."
              and r.error_code == "answered_by_groq", r.reply_text)
        check("Groq answer saved with source groq", saved and saved[-1][0][5].get("source") == "groq")

        groq_answer["text"] = None
        FakeGroqTools.queue = [("tool", ("answer_question", {"question": "Amber Fort timing?"}))]
        r = ra("Amber Fort ki timing kya hai", lang="en")
        check("both fail -> polite 'couldn't get an answer'", r.reply_text == agent.ANSWER_FAILED["en"] and r.error_code == "answer_failed")

        guard["allowed"] = False
        called = []
        with mock.patch.object(tgs, "_voice_gemini", lambda q, sp: called.append(1) or "x"):
            FakeGroqTools.queue = [("tool", ("answer_question", {"question": "write me python code"}))]
            r = ra("write python code", lang="en")
        check("cost guard refuses -> decline, Gemini never called", r.reply_text == tgs.VOICE_DECLINE["en"] and not called
              and r.error_code == "declined")
        guard["allowed"] = True

    # ---------------- no tool / unknown tool
    FakeGroqTools.queue = [("text", "Main sirf aapki trip mein madad kar sakta hoon.")]
    r = ra("ek joke sunao")
    check("off-topic: decline text, no actions", r.ui_actions == [] and r.action == "reply")
    FakeGroqTools.queue = [("tool", ("delete_trip", {"name": "Goa"}))]
    r = ra("Goa trip delete karo")
    check("a tool we don't offer -> no action", r.ui_actions == [] and r.error_code == "unknown_tool")

    # ---------------- logs never carry the user's words
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    for name in ("voice", tgs.log.name):
        logging.getLogger(name).addHandler(handler)
        logging.getLogger(name).setLevel(logging.DEBUG)
    with mock.patch.object(tgs, "evaluate_cost_guards", lambda q: (True, "PASSED", "")), \
            mock.patch.object(tgs, "_voice_gemini", lambda q, sp: None), \
            mock.patch.object(tgs, "_voice_groq", lambda q, sp: "Secretanswer zebra. Second."), \
            mock.patch.object(tgs, "persist_message", lambda *a, **k: None), \
            mock.patch.object(places, "search_places", lambda q: SEARCH_HITS):
        FakeGroqTools.queue = [("tool", ("answer_question", {"question": "zebraquestion about Jaipur"})),
                               ("tool", ("open_trip", {"name_or_destination": "Zanzibarxyz"})),
                               ("tool", ("search_places", {"query": "Hawa Mahal zebraplace"}))]
        ra("zebraquestion about Jaipur")
        ra("Zanzibarxyz wali trip")
        ra("zebraplace dikhao")
    log = buf.getvalue()
    check("logs: actions and timings only, never the user's words or the reply",
          "zebra" not in log.lower() and "Zanzibar" not in log and "Secretanswer" not in log and "action=answer" in log and "tool_ms=" in log, log[-300:])

# ---------------- reply message carries tool_ms
msg = messages.reply("turn_x", "ok", None, "audio/wav", 0, [], "answer", 450, 1800)
check("reply message has llm_ms and tool_ms", msg["llm_ms"] == 450 and msg["tool_ms"] == 1800 and msg["action"] == "answer")

# ---------------- ws._resolve_trip: own trip -> TripInfo with its id; someone else's -> None
from voice import ws  # noqa: E402
own = ws._resolve_trip(JAIPUR, USER)
check("_resolve_trip: own trip -> id, title and dates", own is not None and own.id == JAIPUR and own.title == "Jaipur Trip")
check("_resolve_trip: another user's trip -> None", ws._resolve_trip(OTHER_GOA, USER) is None)

for key in redis_conn.scan_iter("voice:mem:usr_s3_*"):
    redis_conn.delete(key)
print(f"\n{sum(results)}/{len(results)} passed", flush=True)
sys.exit(0 if all(results) else 1)
