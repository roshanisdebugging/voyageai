"""
Booking step 1: the optional starting city ("Kahan se jaana hai?") in voice trip creation and typed trips.
Run from backend/: python -m tests.test_voice_origin
No model or Google call: the model is a fake that returns the values it would extract, the place search is a fake.
App DB = SQLite (trip creation part); the draft state uses the local Redis (this test's keys are removed at the end).
"""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
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

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'origin.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)
import models_db, models_trip, models_itinerary, models_package, models_place  # noqa: E401,E402,F401
database.Base.metadata.create_all(bind=database.engine)

import openai_client  # noqa: E402
import places  # noqa: E402
import trip_lifecycle  # noqa: E402
from models_place import CityModel  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from trip_lifecycle import TripValidationError, clean_place_name, today_ist  # noqa: E402
from voice import agent, draft as D, pending as P, pipeline  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if (detail != "" and not cond) else ""), flush=True)


TODAY = today_ist()
day = lambda n: TODAY + timedelta(days=n)  # noqa: E731
iso = lambda n: day(n).isoformat()  # noqa: E731
say = lambda n: f"{day(n).day} {D.MONTHS[day(n).month - 1]}"  # noqa: E731
USER = f"usr_org_{uuid.uuid4().hex[:6]}"
CONVS = []


def pl(pid, name, lat, lng, city):
    return [{"id": pid, "place_id": pid, "name": name, "latitude": lat, "longitude": lng, "city": city}]


KOLKATA = pl("ChIJkol", "Kolkata", 22.57, 88.36, "Kolkata, West Bengal, India")
GOA = pl("ChIJgoa", "Goa", 15.29, 74.12, "Goa, India")
PLACES = {"goa": GOA, "गोवा": GOA, "kolkata": KOLKATA, "कोलकाता": KOLKATA, "calcutta": KOLKATA,
          "patna": pl("ChIJpat", "Patna", 25.59, 85.14, "Patna, Bihar, India"),
          "पटना": pl("ChIJpat", "Patna", 25.59, 85.14, "Patna, Bihar, India"),
          "jaipur": pl("ChIJjpr", "Jaipur", 26.91, 75.79, "Jaipur, Rajasthan, India")}
fake_search = lambda q: PLACES.get(q.strip().lower(), [])  # noqa: E731


class FakeTools:
    """The model: returns the tool call queued for this turn; counts calls (no call = code handled the turn)."""
    queue, calls = [], 0

    def __call__(self, messages, tools, **kw):
        FakeTools.calls += 1
        if not FakeTools.queue:
            return {"content": "Abhi samajh nahi paaya, phir se boliye.", "tool_calls": []}
        kind, payload = FakeTools.queue.pop(0)
        if kind == "text":
            return {"content": payload, "tool_calls": []}
        return {"content": None, "tool_calls": [{"name": "update_trip_draft", "arguments": payload}]}


def new_conv():
    c = f"conv_org_{uuid.uuid4().hex[:6]}"
    CONVS.append(c)
    return c


def ra(text, conv, args=None, lang="hi"):
    """One voice turn. args = what the model extracts from `text` (None = the model is not reached / says text)."""
    FakeTools.queue = [("tool", args)] if args is not None else []
    return agent.run_agent(text, lang, user_id=USER, conversation_id=conv, screen="/home", trip=None, redis_conn=redis_conn)


def no_llm(fn):
    before = FakeTools.calls
    r = fn()
    return r, FakeTools.calls == before


def dr(conv):
    return D.load(redis_conn, USER, conv)


ALL = {"start_date": iso(20), "end_date": iso(23), "adults": 2, "children": 0, "budget_inr": 50000}
RB_HI = f"{say(20)} se {say(23)}, teen raat. Sahi hai?"            # today's read-back (no origin): unchanged
RB_EN = f"{say(20)} to {say(23)}, 3 nights. Is that right?"
RB = {"hi": RB_HI, "en": RB_EN}
L = lambda text: agent.template_language("hi", text)  # noqa: E731  (the reply language the app picks for these words)
T_KG = "Kolkata se Goa jaana hai, do log, budget pachaas hazaar"     # what was said (the model's values are in args)
T_G = "Goa jaana hai, do log, budget pachaas hazaar"
T_KG_EN = "From Kolkata to Goa for two adults"
T_G_EN = "I want to go to Goa"

# ---------------------------------------------------------------- the name rule (code checks what the model gave)
for raw, want in [("Kolkata", "Kolkata"), ("  New   Delhi ", "New Delhi"), ("कोलकाता", "कोलकाता"), ("Port Blair", "Port Blair"),
                  ("Sawai Madhopur", "Sawai Madhopur"), ("St. Thomas Mount", "St. Thomas Mount"), ("Daman & Diu", "Daman & Diu"),
                  ("12345", None), ("Sector 17", None), ("", None), ("K", None), ("x" * 61, None), (12, None), (None, None),
                  ("Kolkata!!", None), ("<script>", None), ("--", None)]:
    check(f"clean_place_name({str(raw)[:20]!r}) == {want!r}", clean_place_name(raw) == want, clean_place_name(raw))

# ---------------------------------------------------------------- skip words
for t in ["pata nahi", "Pata nahi.", "mujhe pata nahi", "nahi pata", "chhodo", "chhod do", "abhi nahi", "skip", "skip karo",
          "पता नहीं", "पता नहीं।", "मुझे पता नहीं", "छोड़ो", "अभी नहीं", "I don't know", "don't know", "no idea", "not sure"]:
    check(f"is_origin_skip({t!r})", agent.is_origin_skip(t))
for t in ["Kolkata", "Kolkata se", "nahi", "haan", "पता नहीं कोलकाता से", "pata nahi Patna se", "हाँ", "50 hazaar", ""]:
    check(f"not a skip: {t!r}", not agent.is_origin_skip(t))

# ---------------------------------------------------------------- the asking order (cap of two)
check("questions: destination + dates first (origin waits)", D.ask_fields(D.TripDraftState().missing_fields(), True) == ["destination", "start_date"])
check("questions: dates + adults missing -> no origin (no third question)",
      D.ask_fields(["start_date", "end_date", "adults"], True) == ["start_date", "adults"])
check("questions: only budget missing -> budget + origin", D.ask_fields(["budget_inr"], True) == ["budget_inr", "origin_city"])
check("questions: nothing missing -> origin alone", D.ask_fields([], True) == ["origin_city"])
check("question text (hi)", D.question_for(["budget_inr"], "hi", ask_origin=True) == "Kul budget kitna hai? Kahan se jaana hai?")
check("question text (en)", D.question_for([], "en", ask_origin=True) == "Where are you starting from?")

with mock.patch.object(openai_client, "chat_tools", FakeTools()), mock.patch.object(places, "search_places", fake_search):

    # ---------------- 1. everything in one sentence, origin included (Hinglish / Devanagari / English)
    for lang, text, args, want in [
        ("hi", "Kolkata se Goa, 20 se 23, do bade log, koi bachcha nahi, budget 50 hazaar",
         {"origin_city": "Kolkata", "destination": "Goa", **ALL}, f"Kolkata se Goa, {say(20)} se {say(23)}, teen raat, do bade log. Sahi hai?"),
        ("hi", "कोलकाता से गोवा, ...", {"origin_city": "कोलकाता", "destination": "गोवा", **ALL},
         f"Kolkata se Goa, {say(20)} se {say(23)}, teen raat, do bade log. Sahi hai?"),
        ("en", "From Kolkata to Goa, ...", {"origin_city": "Kolkata", "destination": "Goa", **ALL},
         f"Kolkata to Goa, {say(20)} to {say(23)}, 3 nights, 2 adults. Is that right?"),
    ]:
        c = new_conv()
        r = ra(text, c, args, lang)
        check(f"[{lang}] all in one sentence with origin -> read-back with origin, no origin question",
              r.step == "confirm_date" and r.reply_text.endswith(want) and "Kahan se" not in r.reply_text, r.reply_text)
        r, quiet = no_llm(lambda: ra("haan", c, lang=lang))
        check(f"[{lang}] 'haan' -> ready, prefill carries the origin", r.step == "ready" and quiet
              and r.ui_actions[0]["prefill"]["origin"]["name"] == "Kolkata", r.step)

    # ---------------- 2. details one by one (Hinglish): origin only in a free slot, after the required ones
    c = new_conv()
    r = ra("Goa jaana hai", c, {"destination": "Goa"})
    check("1-by-1: 'Goa jaana hai' -> no origin set, dates + adults asked (no third question)",
          r.reply_text == "Goa. Kab se kab tak jaana hai? Kitne bade log jaa rahe hain?" and dr(c).origin_city is None, r.reply_text)
    r = ra("20 se 23", c, {"start_date": iso(20), "end_date": iso(23)})
    check("1-by-1: dates -> adults + children (still no origin)", r.reply_text == "Kitne bade log jaa rahe hain? Koi bachcha bhi saath hai?", r.reply_text)
    r = ra("do log, koi bachcha nahi", c, {"adults": 2, "children": 0})
    check("1-by-1: people -> budget + origin (free slot)", r.reply_text == "Kul budget kitna hai? Kahan se jaana hai?", r.reply_text)
    check("1-by-1: origin asked once, recorded in the draft", dr(c).origin_asked == 1 and dr(c).origin_pending)
    r = ra("50 hazaar, Kolkata se", c, {"budget_inr": 50000, "origin_city": "Kolkata"})
    check("1-by-1: budget + origin -> read-back with origin",
          r.reply_text == f"Kolkata se Goa, {say(20)} se {say(23)}, teen raat, do bade log. Sahi hai?", r.reply_text)

    # English one by one
    c = new_conv()
    ra("I want to go to Goa", c, {"destination": "Goa"}, "en")
    ra("20th to 23rd", c, {"start_date": iso(20), "end_date": iso(23)}, "en")
    r = ra("two adults, no kids", c, {"adults": 2, "children": 0}, "en")
    check("[en] 1-by-1: budget + origin asked", r.reply_text == "What's the total budget? Where are you starting from?", r.reply_text)
    r, quiet = no_llm(lambda: ra("I don't know", c, lang="en"))
    check("[en] 'I don't know' (both asked) -> origin skipped, budget asked again, no LLM call",
          quiet and dr(c).origin_skipped and r.reply_text == "Okay, without a starting city. What's the total budget?", r.reply_text)
    r = ra("50 thousand", c, {"budget_inr": 50000}, "en")
    check("[en] then the read-back stays exactly as today (no origin)", r.reply_text == RB_EN, r.reply_text)

    # ---------------- 3. origin said first
    c = new_conv()
    r = ra("Kolkata se jaana hai", c, {"origin_city": "Kolkata"})
    check("origin first: kept, destination + dates asked", dr(c).origin_city["name"] == "Kolkata"
          and r.reply_text == "Kahan jaana hai? Kab se kab tak jaana hai?", r.reply_text)
    r = ra("Goa, 20 se 23, do log, bachcha nahi, 50 hazaar", c, {"destination": "Goa", **ALL})
    check("origin first: never asked for it, read-back with it", dr(c).origin_asked == 0
          and r.reply_text.endswith(f"Kolkata se Goa, {say(20)} se {say(23)}, teen raat, do bade log. Sahi hai?"), r.reply_text)
    c = new_conv()
    r = ra("मुझे पटना से जाना है", c, {"origin_city": "पटना"})
    check("[Devanagari] origin first: पटना -> Patna kept", (dr(c).origin_city or {}).get("name") == "Patna", r.reply_text)

    # ---------------- 4. origin never said: asked once (alone, all else given), then not again
    for lang, skip_text in [("hi", None), ("en", None)]:
        c = new_conv()
        r = ra(T_G if lang == "hi" else T_G_EN, c, {"destination": "Goa", **ALL}, lang)
        q = "Goa. Kahan se jaana hai?" if lang == "hi" else "Where are you starting from?"
        check(f"[{lang}] never said: all required given -> origin asked alone", r.reply_text.endswith(q.split(". ")[-1]) and r.step == "ask", r.reply_text)
        r = ra("budget 60 hazaar kar do", c, {"budget_inr": 60000}, lang)   # an answer without the origin
        check(f"[{lang}] never said: an answer without it -> skipped, read-back as today",
              dr(c).origin_skipped and r.step == "confirm_date" and "Kahan se" not in r.reply_text and "starting" not in r.reply_text, r.reply_text)
        check(f"[{lang}] never said: asked exactly once", dr(c).origin_asked == 1)

    # ---------------- 5. "pata nahi" / "chhodo" / "पता नहीं" / "abhi nahi": skipped, no LLM call, read-back unchanged
    for text in ["pata nahi", "पता नहीं।", "chhodo", "abhi nahi", "skip karo", "छोड़ो"]:
        c = new_conv()
        ra(T_G, c, {"destination": "Goa", **ALL})
        r, quiet = no_llm(lambda: ra(text, c))
        check(f"{text!r} -> no origin, read-back exactly as today, no LLM call",
              quiet and r.reply_text == f"{agent.ORIGIN_SKIPPED[L(text)]} {RB[L(text)]}" and dr(c).origin_skipped, r.reply_text)
        r, quiet = no_llm(lambda: ra("haan", c))
        check(f"{text!r} -> 'haan' -> ready without origin", r.step == "ready" and r.ui_actions[0]["prefill"]["origin"] is None)

    # ---------------- 6. "Kolkata se Goa" / "Goa jaana hai" (what code does with the model's split)
    c = new_conv()
    ra("Kolkata se Goa jaana hai", c, {"origin_city": "Kolkata", "destination": "Goa"})
    check("'Kolkata se Goa' -> origin Kolkata, destination Goa", dr(c).origin_city["name"] == "Kolkata" and dr(c).destination["name"] == "Goa")
    c = new_conv()
    ra("Goa jaana hai", c, {"destination": "Goa", "origin_city": None})
    check("'Goa jaana hai' -> no origin", dr(c).origin_city is None and not dr(c).origin_skipped)
    check("the prompt tells the model how to split origin and destination",
          "Kolkata se Goa" in agent.SYSTEM_PROMPT and "\"Goa jaana hai\" alone -> destination=Goa, NO origin_city" in agent.SYSTEM_PROMPT)

    # ---------------- 7. origin = destination: asked once
    for yes in ["haan", "हाँ", "bilkul"]:
        c = new_conv()
        r = ra("Goa se Goa", c, {"origin_city": "Goa", "destination": "Goa", **ALL})
        check(f"same place -> asked to confirm once", r.step == "confirm_origin" and r.reply_text.endswith("Goa se Goa hi jaana hai? Sahi hai?"), r.reply_text)
        r, quiet = no_llm(lambda: ra(yes, c))
        check(f"same place + {yes!r} -> kept, read-back with it", quiet and dr(c).origin_city and dr(c).origin_same_ok
              and r.step == "confirm_date" and ("Goa se Goa," if L(yes) == "hi" else "Goa to Goa,") in r.reply_text, r.reply_text)
    for no in ["nahi", "नहीं"]:
        c = new_conv()
        ra("Goa se Goa", c, {"origin_city": "Goa", "destination": "Goa", **ALL})
        r, quiet = no_llm(lambda: ra(no, c))
        check(f"same place + {no!r} -> origin dropped, not asked again, read-back as today",
              quiet and dr(c).origin_city is None and dr(c).origin_skipped and r.reply_text == f"Theek hai. {RB_HI}", r.reply_text)
    c = new_conv()
    ra("Goa se Goa", c, {"origin_city": "Goa", "destination": "Goa", **ALL})
    r = ra("nahi, Patna se", c, {"origin_city": "Patna"})
    check("same place + 'nahi, Patna se' -> Patna, read back", r.reply_text.startswith("Patna se Goa,"), r.reply_text)
    c = new_conv()
    ra("from Goa to Goa", c, {"origin_city": "Goa", "destination": "Goa", **ALL}, "en")
    r = ra("yes", c, lang="en")
    check("[en] same place -> yes -> kept", r.reply_text.startswith("Okay. Goa to Goa,"), r.reply_text)

    # ---------------- 8. correcting only the origin at the read-back
    for lang, text, city, want_start in [("hi", "nahi, Patna se", "Patna", "Patna se Goa,"), ("hi", "नहीं, पटना से", "पटना", "Patna se Goa,"),
                                         ("en", "no, from Patna", "Patna", "Patna to Goa,")]:
        c = new_conv()
        ra(T_KG if lang == "hi" else T_KG_EN, c, {"origin_city": "Kolkata", "destination": "Goa", **ALL}, lang)
        before = dr(c)
        r = ra(text, c, {"origin_city": city}, lang)
        after = dr(c)
        check(f"[{lang}] {text!r} -> only the origin changes, read back again",
              r.step == "confirm_date" and r.reply_text.startswith(want_start)
              and (after.start_date, after.end_date, after.adults, after.budget_inr, after.destination["name"])
              == (before.start_date, before.end_date, before.adults, before.budget_inr, before.destination["name"]), r.reply_text)
        r = ra("haan" if lang != "en" else "yes", c, lang=lang)
        check(f"[{lang}] then yes -> ready with Patna", r.step == "ready" and r.ui_actions[0]["prefill"]["origin"]["name"] == "Patna")
    # after the Confirm card: "nahi, Patna se" also reads back again (pending dropped)
    c = new_conv()
    ra(T_KG, c, {"origin_city": "Kolkata", "destination": "Goa", **ALL})
    ra("haan", c)
    r = ra("nahi, Patna se", c, {"origin_city": "Patna"})
    check("on the Confirm card 'nahi, Patna se' -> pending dropped, read back with Patna",
          P.get(redis_conn, USER, c) is None and r.step == "confirm_date" and r.reply_text.startswith("Patna se Goa,"), r.reply_text)

    # ---------------- 9. a city the search can't find: asked once more, then dropped (never a third time)
    c = new_conv()
    ra(T_G, c, {"destination": "Goa", **ALL})                                     # asks "Kahan se jaana hai?" (1)
    r = ra("Kolkatta se", c, {"origin_city": "Kolkatta"})
    check("not found -> 'Kolkatta nahi mila, phir se bolenge ya skip karein?'",
          r.reply_text == "Kolkatta nahi mila, phir se bolenge ya skip karein?" and dr(c).origin_asked == 2 and dr(c).origin_pending, r.reply_text)
    r = ra("Calcutta se jaana hai", c, {"origin_city": "Calcutta"})
    check("second try found -> read-back with it", r.reply_text.startswith("Kolkata se Goa,"), r.reply_text)
    c = new_conv()
    ra(T_G, c, {"destination": "Goa", **ALL})
    ra("Kolkatta se", c, {"origin_city": "Kolkatta"})
    r = ra("Kolkataa se jaana hai", c, {"origin_city": "Kolkataa"})
    check("second miss -> dropped with a note, read-back as today",
          r.reply_text == f"Kolkataa bhi nahi mila, starting city ke bina aage badhte hain. {RB_HI}" and dr(c).origin_skipped, r.reply_text)
    r = ra("Kolkattaa se", c, {"origin_city": "Kolkattaa"})
    check("never a third question: a later miss is not asked about again", "phir se bolenge" not in r.reply_text
          and not dr(c).origin_pending and dr(c).origin_asked == 2, r.reply_text)
    check("asked at most twice", dr(c).origin_asked <= 2)
    c = new_conv()
    ra(T_G, c, {"destination": "Goa", **ALL})
    r, quiet = no_llm(lambda: ra("Kolkatta se", c, {"origin_city": "Kolkatta"}))
    r, quiet = no_llm(lambda: ra("skip", c))
    check("not found, then 'skip' -> skipped, no LLM call", quiet and dr(c).origin_skipped and r.reply_text.endswith(RB[L("skip")]), r.reply_text)
    c = new_conv()
    r = ra("Kolkatta se Goa ...", c, {"origin_city": "Kolkatta", "destination": "Goa", **ALL})
    check("volunteered but not found -> asked once more", r.reply_text == "Kolkatta nahi mila, phir se bolenge ya skip karein?", r.reply_text)
    r = ra("Kolkataa se jaana hai", c, {"origin_city": "Kolkataa"})
    check("volunteered, second miss -> dropped", dr(c).origin_skipped and r.reply_text.endswith(RB_HI), r.reply_text)

    # ---------------- 10. not a place name -> treated as not given
    for bad in ["12345", "x" * 70, "Sector 17"]:
        c = new_conv()
        ra(T_G, c, {"destination": "Goa", **ALL})
        r = ra("Sector satrah se jaana hai", c, {"origin_city": bad})
        check(f"origin {bad[:12]!r} discarded (not given) -> skipped, read-back as today",
              dr(c).origin_city is None and dr(c).origin_skipped and r.reply_text == RB_HI, r.reply_text)

    # ---------------- 11. yes / no at the read-back (with an origin) still work as before
    for said, want_step in [("haan", "ready"), ("हाँ", "ready"), ("bilkul", "ready"), ("हाँ।", "ready"), ("सही है", "ready")]:
        c = new_conv()
        ra(T_KG, c, {"origin_city": "Kolkata", "destination": "Goa", **ALL})
        r, quiet = no_llm(lambda: ra(said, c))
        check(f"read-back + {said!r} -> {want_step}, no LLM call", r.step == want_step and quiet, r.step)
    for said in ["nahi", "नहीं"]:
        c = new_conv()
        ra(T_KG, c, {"origin_city": "Kolkata", "destination": "Goa", **ALL})
        r, quiet = no_llm(lambda: ra(said, c))
        check(f"read-back + {said!r} -> dates cleared, asked again (as before), origin kept",
              quiet and r.reply_text == agent.DATE_AGAIN["hi"] and dr(c).start_date is None and dr(c).origin_city["name"] == "Kolkata", r.reply_text)
    c = new_conv()
    ra(T_KG, c, {"origin_city": "Kolkata", "destination": "Goa", **ALL})
    tr = SimpleNamespace(text="", language="hi")
    pipeline.decide_reply(SimpleNamespace(user_id=USER, conversation_id=c, session_id=c, screen="/home", trip=None, location=None,
                                          screen_place=None), tr)
    check("silence (empty transcript) -> fixed reply, read-back still waiting", tr.action == "unclear" and dr(c).awaiting == "date")
    r = ra("(nothing heard)", c)
    check("'(nothing heard)' -> no confirm, read-back still waiting", r.step != "ready" and dr(c).awaiting == "date"
          and P.get(redis_conn, USER, c) is None, (r.step, r.reply_text))

    # ---------------- 12. logs: counts and flags only
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        c = new_conv()
        ra(T_KG, c, {"origin_city": "Kolkata", "destination": "Goa", **ALL})
        ra("haan", c)
    lines = [ln for ln in log.getvalue().splitlines() if ln.startswith("[TRIP DRAFT]")]
    check("log: [TRIP DRAFT] origin_set=true ... source=voice", any("origin_set=true" in ln and "source=voice" in ln for ln in lines), lines)
    check("log: never the city or the user's words", not any(w in log.getvalue() for w in ("Kolkata", "Goa", "haan")), log.getvalue()[-300:])

# ---------------------------------------------------------------- trip creation (typed form and voice prefill)
USR = SimpleNamespace(id=f"usr_org_db_{uuid.uuid4().hex[:6]}")
DEST = {"name": "Goa", "city": "Goa", "country": "India", "latitude": 15.29, "longitude": 74.12}
ORIG = {"name": "Kolkata", "city": "Kolkata", "region": "West Bengal", "country": "India", "latitude": 22.57, "longitude": 88.36}


def create(origin=None, **extra):
    payload = {"destination": DEST, "startDate": iso(20), "endDate": iso(23), "adultsCount": 2, "childrenCount": 0,
               "budgetAmount": 50000, "clientRequestId": f"req_{uuid.uuid4().hex[:8]}", **extra}
    if origin is not None:
        payload["origin"] = origin
    with mock.patch.object(trip_lifecycle, "enqueue_itinerary_generation", lambda tid: True), \
            mock.patch("media_service.media_service.resolve_cover_media", lambda d: {}), database.SessionLocal() as db:
        return trip_lifecycle.create_trip_for_user(db, USR, None, None, payload)


log = io.StringIO()
with contextlib.redirect_stdout(log):
    plain = create()
check("trip without an origin: created as before, origin null", plain["origin"] is None and plain["destination"]["name"] == "Goa")
check("trip without an origin: log origin_set=false", "origin_set=false" in log.getvalue())
with_origin = create(ORIG)
check("trip with an origin: stored as a city and returned", (with_origin["origin"] or {}).get("name") == "Kolkata")
with database.SessionLocal() as db:
    check("one cities row for Kolkata", db.query(CityModel).filter(CityModel.name == "Kolkata").count() == 1)
for bad in [{**ORIG, "name": "Sector 17"}, {**ORIG, "name": "y" * 61}]:
    try:
        create(bad)
        check(f"bad origin name {bad['name'][:10]!r} refused", False)
    except TripValidationError as e:
        check(f"bad origin name {bad['name'][:10]!r} refused", "Starting city" in str(e), str(e))
check("empty origin = no origin", create("")["origin"] is None and create(None)["origin"] is None)

# ---------------------------------------------------------------- clean-up
for c in CONVS:
    D.delete(redis_conn, USER, c)
    P.clear(redis_conn, USER, c)
    agent.clear_memory(redis_conn, USER, c)
database.engine.dispose()
shutil.rmtree(SCRATCH, ignore_errors=True)
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
