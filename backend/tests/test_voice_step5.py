"""
Voice step 5 checks (more actions): app DB = SQLite, Redis = local, Groq + place search simulated.
Shared trip_actions (tap + voice), trip context + name matching by code, small actions with Undo (and the Undo
running through /ws/app from an allowlist), big actions only on confirm (once), swap opens the sheet,
"delete" never deletes, refresh after each change, another user's trip/activity/place refused, logs without words.
Run from backend/: python -m tests.test_voice_step5
"""
import io
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

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'voice5.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
import groq_client  # noqa: E402
import places  # noqa: E402
import task_queue  # noqa: E402
import trip_actions  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from models_db import SavedPlaceModel  # noqa: E402
from models_itinerary import ItineraryActivityModel, ItineraryDayModel, ItineraryModel  # noqa: E402
from models_package import TripExpenseModel  # noqa: E402
from models_trip import TripModel  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from trip_lifecycle import today_ist  # noqa: E402
from voice import agent, context as C, pending as P, pipeline, ws as voice_ws  # noqa: E402
from voice.stt import STTResult  # noqa: E402
from voice.tools import actions as A  # noqa: E402

main.SessionLocal = database.SessionLocal
database.Base.metadata.create_all(bind=database.engine)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


TODAY = today_ist()
d = lambda n: (TODAY + timedelta(days=n)).isoformat()  # noqa: E731
NOW = datetime.now(timezone.utc).isoformat()

client = TestClient(main.app)
client.__enter__()
toks = {}
for name in ("A", "B"):
    r = client.post("/api/auth/register", json={"name": f"Five {name}", "email": f"s5{name.lower()}_{uuid.uuid4().hex[:6]}@example.com",
                                                "password": "secret123"})
    toks[name] = (r.json()["token"], r.json()["user"]["id"])
client.cookies.clear()
tok_a, uid_a = toks["A"]
tok_b, uid_b = toks["B"]
T_A, T_B = f"trip_s5a_{uuid.uuid4().hex[:6]}", f"trip_s5b_{uuid.uuid4().hex[:6]}"


def make_trip(tid, uid, days, dest="Jaipur", start=0):
    with database.SessionLocal() as db:
        db.add(TripModel(id=tid, user_id=uid, title=f"{dest} {tid[-4:]}", status="PLANNING", start_date=d(start),
                         end_date=d(start + len(days) - 1),
                         total_days=len(days), destination={"name": dest}, travelers=[], budget={"targetAmount": 20000},
                         created_at=NOW, updated_at=NOW, itinerary_status="READY"))
        itin = ItineraryModel(id=f"it_{tid}", trip_id=tid, status="READY", created_at=NOW, updated_at=NOW)
        db.add(itin)
        ids = {}
        for n, acts in enumerate(days, start=1):
            day = ItineraryDayModel(id=f"day_{tid}_{n}", itinerary_id=itin.id, day_number=n, date=d(start + n - 1), title=f"Day {n}")
            db.add(day)
            for i, title in enumerate(acts):
                aid = f"act_{tid}_{n}_{i}"
                ids[title] = aid
                db.add(ItineraryActivityModel(id=aid, day_id=day.id, time_slot="10:00 AM", title=title))
        db.commit()
        return ids


ACT_A = make_trip(T_A, uid_a, [["Visit Hawa Mahal", "Amber Fort", "Lunch at LMB"], ["City Palace", "Lunch at Rawat"]])
ACT_B = make_trip(T_B, uid_b, [["Nahargarh Fort"]])
TRIP_A = agent.TripInfo(title="Jaipur", start_date=d(0), end_date=d(1), id=T_A)


def is_done(aid):
    with database.SessionLocal() as db:
        return bool(db.query(ItineraryActivityModel).filter(ItineraryActivityModel.id == aid).first().is_done)


def expenses(tid):
    with database.SessionLocal() as db:
        return [(e.title, e.amount, e.category) for e in db.query(TripExpenseModel).filter(TripExpenseModel.trip_id == tid).all()]


def saved(uid):
    with database.SessionLocal() as db:
        return {r.place_id: r.title for r in db.query(SavedPlaceModel).filter(SavedPlaceModel.user_id == uid).all()}


def ws_app(token, action, payload):
    with client.websocket_connect("/ws/app") as ws:
        ws.send_json({"id": "x", "action": action, "payload": {**payload, "token": token}})
        while True:
            f = ws.receive_json()
            if f.get("id") == "x":
                return f


def run_undo(token, toast):
    """What the app's Undo button does: the allowlisted /ws/app action with the toast's payload."""
    assert toast["undo"]["action"] in A.UNDO_ALLOWLIST
    return ws_app(token, toast["undo"]["action"], toast["undo"]["payload"])


PLACES = {"hawa mahal": [{"id": "ChIJhawa", "place_id": "ChIJhawa", "name": "Hawa Mahal", "latitude": 26.92, "longitude": 75.82,
                          "city": "Jaipur, Rajasthan, India"}]}
fake_search = lambda q: PLACES.get(q.strip().lower(), [])  # noqa: E731


class FakeTools:
    queue, calls = [], []

    def __call__(self, messages, tools, **kw):
        FakeTools.calls.append(messages)
        kind, payload = FakeTools.queue.pop(0)
        if kind == "tool":
            return {"content": None, "tool_calls": [{"name": payload[0], "arguments": payload[1]}]}
        return {"content": payload, "tool_calls": []}


fake = FakeTools()


def ra(text, conv, queue=None, user=None, trip=TRIP_A, screen="/trip", screen_place=None):
    if queue is not None:
        FakeTools.queue = list(queue)
    return agent.run_agent(text, "hi", user_id=user or uid_a, conversation_id=conv, screen=screen, trip=trip,
                           redis_conn=redis_conn, screen_place=screen_place)


def types(r):
    return [a["type"] for a in r.ui_actions]


def toast_of(r):
    return next((a for a in r.ui_actions if a["type"] == "undo_toast"), None)


# ---------------- trip context + matching by code
ctx = C.load(uid_a, T_A)
check("context: the owner's trip loads with its 5 activities", ctx is not None and len(ctx.activities) == 5)
check("context: another user's trip is never loaded", C.load(uid_b, T_A) is None)
text = C.prompt_text(ctx)
check("context: days with dates, today first, short IDs + names, spent vs budget",
      f"Day 1 ({d(0)}, today): a1 Visit Hawa Mahal; a2 Amber Fort; a3 Lunch at LMB" in text and f"Day 2 ({d(1)})" in text
      and "Spent Rs 0 of Rs 20,000 budget" in text, text)
check("match: a name", C.match_activity(ctx, "Hawa Mahal")[0].id == ACT_A["Visit Hawa Mahal"])
check("match: a short ID", C.match_activity(ctx, "a4")[0].id == ACT_A["City Palace"])
check("match: a speech-to-text typo", (C.match_activity(ctx, "hawa mehal")[0] or C.Act("", "", "", 0, "", False)).id == ACT_A["Visit Hawa Mahal"])
m_, cands = C.match_activity(ctx, "lunch")
check("match: two lunches -> no guess, both offered", m_ is None and len(cands) == 2)
check("match: an unknown name -> nothing", C.match_activity(ctx, "Taj Mahal") == (None, []))
check("match: another trip's activity ID is not in this trip", C.match_activity(ctx, ACT_B["Nahargarh Fort"]) == (None, []))

buf = io.StringIO()
handler = logging.StreamHandler(buf)
logging.getLogger("voice").addHandler(handler)
logging.getLogger("voice").setLevel(logging.INFO)

with mock.patch.object(groq_client, "groq_chat_tools", fake), mock.patch.object(places, "search_places", fake_search):
    CV = f"conv_s5_{uuid.uuid4().hex[:6]}"

    # ---------------- small: mark done (+ Undo through /ws/app)
    with mock.patch.object(trip_actions, "set_activity_done", wraps=trip_actions.set_activity_done) as spy:
        t0 = time.perf_counter()
        r = ra("Hawa Mahal done ho gaya", CV, [("tool", ("mark_activity_done", {"activity": "Hawa Mahal"}))])
        small_ms = (time.perf_counter() - t0) * 1000
        check("voice mark done runs through trip_actions.set_activity_done", spy.call_count == 1)
        check("the prompt carries the trip plan", "a1 Visit Hawa Mahal" in FakeTools.calls[-1][0]["content"])
        check("mark done: runs now, reply names it", is_done(ACT_A["Visit Hawa Mahal"]) and r.reply_text == "Visit Hawa Mahal done mark kar diya."
              and r.action == "mark_done", r.reply_text)
        t = toast_of(r)
        check("mark done: refresh itinerary + Undo toast (done=false)", types(r) == ["refresh", "undo_toast"]
              and r.ui_actions[0]["what"] == "itinerary" and t["undo"] == {"action": "trips:set_activity_done", "payload": {
                  "trip_id": T_A, "activity_id": ACT_A["Visit Hawa Mahal"], "done": False}}, r.ui_actions)
        f = run_undo(tok_b, t)
        check("Undo payload run by ANOTHER user is refused, nothing changes", f.get("error") and is_done(ACT_A["Visit Hawa Mahal"]), f.get("error"))
        f = run_undo(tok_a, t)
        check("Undo (tap) reverses it through /ws/app trips:set_activity_done (same shared action)",
              not f.get("error") and not is_done(ACT_A["Visit Hawa Mahal"]) and spy.call_count == 2, f.get("error"))
        f = ws_app(tok_a, "trips:set_activity_done", {"trip_id": T_A, "activity_id": ACT_A["Amber Fort"], "done": True})
        check("tap path: trips:set_activity_done still answers the same shape", f["data"]["isDone"] is True
              and f["data"]["progress"]["completedActivitiesCount"] == 1, f)
        ws_app(tok_a, "trips:set_activity_done", {"trip_id": T_A, "activity_id": ACT_A["Amber Fort"], "done": False})
        f = ws_app(tok_a, "trips:set_activity_done", {"trip_id": T_A, "activity_id": ACT_B["Nahargarh Fort"], "done": True})
        check("tap path: an activity of another user's trip is refused", f.get("error") and not is_done(ACT_B["Nahargarh Fort"]))
    check("small action code time measured", small_ms < 5000, f"{small_ms:.0f} ms")

    r = ra("Taj Mahal ho gaya", CV, [("tool", ("mark_activity_done", {"activity": "Taj Mahal"}))])
    check("unknown activity name -> a question, nothing changed", r.action == "ask_activity" and r.ui_actions == []
          and "Kaunsi activity" in r.reply_text, r.reply_text)
    r = ra("lunch done", CV, [("tool", ("mark_activity_done", {"activity": "lunch"}))])
    check("two matches -> asks which one (never guesses)", r.action == "ask_activity" and "Lunch at LMB" in r.reply_text
          and "Lunch at Rawat" in r.reply_text and not is_done(ACT_A["Lunch at LMB"]), r.reply_text)
    r = ra("woh done karo", CV, [("tool", ("mark_activity_done", {"activity": ACT_B["Nahargarh Fort"]}))])
    check("model gives another user's activity ID -> question, never touched", r.action == "ask_activity"
          and not is_done(ACT_B["Nahargarh Fort"]))
    r = ra("Nahargarh done", CV, [("tool", ("mark_activity_done", {"activity": "Nahargarh Fort"}))],
           trip=agent.TripInfo(title="x", start_date=None, end_date=None, id=T_B))
    check("another user's trip as the open trip -> no context, nothing done", r.action == "ask_trip" and not is_done(ACT_B["Nahargarh Fort"]))
    check("ws: another user's trip is never resolved as the open trip", voice_ws._resolve_trip(T_B, uid_a) is None)
    r = ra("Hawa Mahal ho gaya", CV, [("tool", ("mark_activity_done", {"activity": "Hawa Mahal", "done": False}))])
    check("done=false unmarks, Undo marks again", not is_done(ACT_A["Visit Hawa Mahal"]) and toast_of(r)["undo"]["payload"]["done"] is True)

    # ---------------- small: save / unsave a place (+ Undo)
    with mock.patch.object(trip_actions, "save_place", wraps=trip_actions.save_place) as sp_save, \
            mock.patch.object(trip_actions, "unsave_place", wraps=trip_actions.unsave_place) as sp_unsave:
        r = ra("yeh jagah save karo", CV, [("tool", ("save_place", {"place": None}))])
        check("save with no place on screen or searched -> asks, nothing saved", r.action == "ask_place" and saved(uid_a) == {})
        ra("Hawa Mahal dikhao", CV, [("tool", ("search_places", {"query": "Hawa Mahal", "show": True}))])
        r = ra("yeh jagah save karo", CV, [("tool", ("save_place", {"place": None}))])
        check("save: the last searched place, runs now", saved(uid_a) == {"ChIJhawa": "Hawa Mahal"} and r.reply_text == "Hawa Mahal save kar diya.")
        t = toast_of(r)
        check("save: refresh saved_places + Undo = places:unsave", types(r) == ["refresh", "undo_toast"]
              and r.ui_actions[0]["what"] == "saved_places" and t["undo"] == {"action": "places:unsave", "payload": {"place_id": "ChIJhawa"}})
        r2 = ra("save karo", CV, [("tool", ("save_place", {"place": "Hawa Mahal"}))])
        check("already saved -> says so, no Undo (an Undo would remove the older save)", toast_of(r2) is None and "pehle se" in r2.reply_text)
        rb = client.post("/api/places/save", json={"place_id": "ChIJhawa", "title": "Hawa Mahal"}, headers={"Authorization": f"Bearer {tok_b}"})
        check("tap path (REST save) runs through trip_actions.save_place", rb.status_code == 200 and sp_save.call_count == 2)
        f = run_undo(tok_a, t)
        check("Undo of save removes only A's saved place (B's stays)", not f.get("error") and saved(uid_a) == {}
              and saved(uid_b) == {"ChIJhawa": "Hawa Mahal"} and sp_unsave.call_count == 1, f.get("error"))
        ra("save", CV, [("tool", ("save_place", {}))])
        r = ra("Hawa Mahal saved se hatao", CV, [("tool", ("unsave_place", {"place": "Hawa Mahal"}))])
        t = toast_of(r)
        check("unsave: runs now, Undo = places:save with the place's details", saved(uid_a) == {} and r.action == "unsave_place"
              and t["undo"]["action"] == "places:save" and t["undo"]["payload"]["title"] == "Hawa Mahal", r.ui_actions)
        f = run_undo(tok_a, t)
        check("Undo of unsave saves it again", not f.get("error") and saved(uid_a) == {"ChIJhawa": "Hawa Mahal"}, f.get("error"))
        r = ra("Taj Mahal saved se hatao", CV, [("tool", ("unsave_place", {"place": "Taj Mahal"}))])
        check("unsave a place that isn't saved -> says so", r.action == "ask_place" and saved(uid_a) == {"ChIJhawa": "Hawa Mahal"})
        client.delete("/api/places/save/ChIJhawa", headers={"Authorization": f"Bearer {tok_a}"})
        check("tap path (REST delete) runs through trip_actions.unsave_place", saved(uid_a) == {} and sp_unsave.call_count >= 3)
    CD = f"conv_s5d_{uuid.uuid4().hex[:6]}"
    r = ra("yeh jagah save karo", CD, [("tool", ("save_place", {}))], screen="/details/ChIJcity",
           screen_place={"place_id": "ChIJcity", "name": "City Palace Museum", "address": "Jaipur"})
    check("save: the place page on screen", saved(uid_a).get("ChIJcity") == "City Palace Museum", r.reply_text)
    check("ws: screen place only on its own /details page, checked shape",
          voice_ws._screen_place({"place_id": "ChIJx", "name": "X"}, "/home") is None
          and voice_ws._screen_place({"place_id": "bad id!", "name": "X"}, "/details/bad id!") is None
          and voice_ws._screen_place({"place_id": "ChIJx", "name": "X"}, "/details/ChIJx") == {"place_id": "ChIJx", "name": "X", "address": ""})
    try:
        A.undo_toast("x", "trips:delete", {"trip_id": T_A})
        refused = False
    except ValueError:
        refused = True
    check("Undo allowlist: trips:delete is refused", refused)
    check("Undo allowlist is exactly the three actions", A.UNDO_ALLOWLIST == {"trips:set_activity_done", "places:save", "places:unsave"})

    # ---------------- big: add expense (pending; confirm once)
    CE = f"conv_s5e_{uuid.uuid4().hex[:6]}"
    with mock.patch.object(trip_actions, "add_expense", wraps=trip_actions.add_expense) as spy:
        t0 = time.perf_counter()
        r = ra("auto ka 350 add karo", CE, [("tool", ("add_expense", {"title": "Auto", "amount": 350, "category": "transport"}))])
        check("add_expense: pending, nothing saved yet", expenses(T_A) == [] and r.action == "expense_pending"
              and r.reply_text == "₹350, Auto, transport mein add karun?" and r.pending_confirmation["summary"] == r.reply_text, r.reply_text)
        pid = r.pending_confirmation["id"]
        n = len(FakeTools.calls)
        r = ra("haan", CE)
        big_ms = (time.perf_counter() - t0) * 1000
        check("'haan' -> added once via trip_actions (no LLM call), refresh expenses",
              expenses(T_A) == [("Auto", 350.0, "Transport")] and spy.call_count == 1 and len(FakeTools.calls) == n
              and r.ui_actions == [{"type": "refresh", "what": "expenses"}] and r.action == "expense_added", r.reply_text)
        r = ra("haan", CE)
        check("second 'haan' does nothing", len(expenses(T_A)) == 1 and r.action != "expense_added")
        check("button confirm with the old pending id does nothing", agent.confirm_pending(redis_conn, uid_a, CE, "hi", pid).action == "confirm_none"
              and len(expenses(T_A)) == 1)
        r = ra("khane ka 1200 kharcha", CE, [("tool", ("add_expense", {"title": "Khana", "amount": 1200, "category": "food"}))])
        r = ra("nahi", CE)
        check("'nahi' -> nothing saved", len(expenses(T_A)) == 1 and r.reply_text == "Theek hai, kuch nahi badla.", r.reply_text)
        r = ra("khane ka kharcha add karo", CE, [("tool", ("add_expense", {"title": "Khana", "amount": 0, "category": "food"}))])
        check("no amount -> asks, no pending", r.action == "ask_amount" and P.get(redis_conn, uid_a, CE) is None)
        r = ra("1200 ka khana", CE, [("tool", ("add_expense", {"title": "Khana", "amount": 1200, "category": "food"}))])
        r = ra("Hawa Mahal kahan hai", CE, [("tool", ("search_places", {"query": "Hawa Mahal", "show": False}))])
        check("a new topic drops the pending expense", P.get(redis_conn, uid_a, CE) is None and len(expenses(T_A)) == 1)
        res = A.run_add_expense(uid_a, {"trip_id": T_B, "title": "x", "amount": 100, "category": "food"}, "hi")
        check("confirm re-checks the trip: another user's trip refused", res.action == "expense_failed" and expenses(T_B) == [])
        f = ws_app(tok_a, "trips:add_expense", {"trip_id": T_A, "title": "Chai", "amount": 40, "category": "Food"})
        check("tap path: trips:add_expense runs through trip_actions, same shape", spy.call_count == 3 and f["data"]["title"] == "Chai"
              and set(f["data"]) == {"id", "tripId", "title", "amount", "category", "paidBy", "isSplit", "createdAt", "description", "date"}, f)
        f = ws_app(tok_b, "trips:add_expense", {"trip_id": T_A, "title": "Hack", "amount": 1})
        check("tap path: another user's trip refused", f.get("error") and len(expenses(T_A)) == 2)
    check("big action code time measured", big_ms < 5000, f"{big_ms:.0f} ms")

    # ---------------- big: regenerate (pending; AI rate-limit bucket on confirm)
    queued = []
    with mock.patch.object(task_queue, "enqueue_itinerary_generation", lambda tid, *a, **k: queued.append(tid)):
        CR = f"conv_s5r_{uuid.uuid4().hex[:6]}"
        r = ra("plan dobara banao", CR, [("tool", ("regenerate_itinerary", {}))])
        check("regenerate: pending with the fixed question, nothing queued", queued == [] and r.action == "regen_pending"
              and r.reply_text == "Poora itinerary dobara banaun? Isme thoda time lagega.", (r.action, r.reply_text, r.error_code))
        for key in redis_conn.scan_iter(f"rl:ws:ai_trip:{uid_a}"):
            redis_conn.delete(key)
        r = ra("haan", CR)
        with database.SessionLocal() as db:
            st = db.query(TripModel).filter(TripModel.id == T_A).first().itinerary_status
        check("'haan' -> queued once, GENERATING, refresh itinerary", queued == [T_A] and st == "GENERATING"
              and r.ui_actions == [{"type": "refresh", "what": "itinerary"}], r.reply_text)
        r = ra("haan", CR)
        check("second 'haan' queues nothing", queued == [T_A])
        with database.SessionLocal() as db:
            db.query(TripModel).filter(TripModel.id == T_A).first().itinerary_status = "READY"
            db.commit()
        now = time.time()
        redis_conn.zadd(f"rl:ws:ai_trip:{uid_a}", {f"{now}:{i}": now for i in range(10)})
        ra("plan dobara banao", CR, [("tool", ("regenerate_itinerary", {}))])
        r = ra("haan", CR)
        check("confirm goes through the AI rate-limit bucket (full -> refused, nothing queued)", r.error_code == "rate_limited" and queued == [T_A])
        redis_conn.delete(f"rl:ws:ai_trip:{uid_a}")
        f = ws_app(tok_a, "trips:regenerate_itinerary", {"trip_id": T_A})
        check("tap path: trips:regenerate_itinerary runs through trip_actions", queued == [T_A, T_A] and f["data"]["status"] == "GENERATING", f)
        with database.SessionLocal() as db:
            db.query(TripModel).filter(TripModel.id == T_A).first().itinerary_status = "READY"
            db.commit()

    # ---------------- swap: opens the sheet; nothing changes by voice
    r = ra("Amber Fort ki jagah kuch aur", CV, [("tool", ("swap_activity", {"activity": "Amber Fort"}))])
    check("swap: opens the swap sheet for that activity, nothing changed", r.ui_actions == [{"type": "open_swap", "trip_id": T_A,
          "activity_id": ACT_A["Amber Fort"], "activity_name": "Amber Fort", "day_number": 1}] and r.action == "swap_open")
    with mock.patch.object(trip_actions, "swap_activity", wraps=trip_actions.swap_activity) as spy:
        f = ws_app(tok_a, "trips:swap_activity", {"trip_id": T_A, "activity_id": ACT_A["Amber Fort"], "replacement": {"name": "Jal Mahal"}})
        f2 = ws_app(tok_b, "trips:swap_activity", {"trip_id": T_A, "activity_id": ACT_A["City Palace"], "replacement": {"name": "Hack"}})
        with database.SessionLocal() as db:
            titles = {a.id: a.title for a in db.query(ItineraryActivityModel).all()}
        check("tap path: trips:swap_activity runs through trip_actions; another user's refused",
              spy.call_count == 1 and titles[ACT_A["Amber Fort"]] == "Jal Mahal" and f2.get("error") and titles[ACT_A["City Palace"]] == "City Palace")

    # ---------------- which trip an action applies to (section 2)
    T_GOA, T_U1, T_U2 = (f"trip_s5{x}_{uuid.uuid4().hex[:6]}" for x in ("g", "u", "v"))
    ACT_G = make_trip(T_GOA, uid_a, [["Baga Beach", "Fort Aguada"]], dest="Goa", start=10)
    make_trip(T_U1, uid_a, [["Lake Pichola"]], dest="Udaipur", start=40)
    make_trip(T_U2, uid_a, [["City Palace Udaipur"]], dest="Udaipur", start=80)
    CT = f"conv_s5t_{uuid.uuid4().hex[:6]}"
    r = ra("Baga Beach ho gaya", CT, [("tool", ("mark_activity_done", {"activity": "Baga Beach"}))], trip=None)
    check("no trip open, none named -> 'Kaun si trip mein?' and nothing else", r.reply_text == "Kaun si trip mein?"
          and r.ui_actions == [] and not is_done(ACT_G["Baga Beach"]), (r.reply_text, r.ui_actions))
    r = ra("auto ka 350", CT, [("tool", ("add_expense", {"title": "Auto", "amount": 350, "category": "transport"}))], trip=None)
    check("no trip open -> asks, no pending", r.reply_text == "Kaun si trip mein?" and P.get(redis_conn, uid_a, CT) is None)
    r = ra("Goa wali trip mein Baga Beach done", CT, [("tool", ("mark_activity_done", {"activity": "Baga Beach", "trip_name": "Goa"}))])
    check("named trip (not the open one): matched by code, the reply names it", is_done(ACT_G["Baga Beach"])
          and r.reply_text == "Goa trip mein Baga Beach done mark kar diya." and toast_of(r)["undo"]["payload"]["trip_id"] == T_GOA, r.reply_text)
    r = ra("Shimla wali trip mein chai 40", CT, [("tool", ("add_expense", {"title": "Chai", "amount": 40, "category": "food", "trip_name": "Shimla"}))])
    check("named trip not found -> 'Is naam ki koi trip nahi mili.'", r.reply_text == "Is naam ki koi trip nahi mili." and P.get(redis_conn, uid_a, CT) is None)
    r = ra("Udaipur wali trip mein chai 40", CT, [("tool", ("add_expense", {"title": "Chai", "amount": 40, "category": "food", "trip_name": "Udaipur"}))])
    check("several matches -> ask by month, nothing pending", r.action == "ask_trip" and "Udaipur ki 2 trips hain" in r.reply_text
          and " wali" in r.reply_text and P.get(redis_conn, uid_a, CT) is None, r.reply_text)
    r = ra("Goa trip mein auto 350", CT, [("tool", ("add_expense", {"title": "Auto", "amount": 350, "category": "transport", "trip_name": "Goa"}))])
    pend = P.get(redis_conn, uid_a, CT)
    check("named big action: confirm line names the trip; pending record carries that trip_id",
          r.reply_text == "Goa trip mein ₹350, Auto, transport add karun?" and pend["data"]["trip_id"] == T_GOA, r.reply_text)
    r = ra("haan", CT)
    check("confirm (Jaipur open, Goa named) -> added to Goa only", expenses(T_GOA) == [("Auto", 350.0, "Transport")]
          and r.action == "expense_added", r.reply_text)
    n_a = len(expenses(T_A))
    r = ra("chai ke 40 rupaye", CT, [("tool", ("add_expense", {"title": "Chai", "amount": 40, "category": "food"}))])
    check("unnamed: the open trip, the line doesn't name it", r.reply_text == "₹40, Chai, khane mein add karun?"
          and P.get(redis_conn, uid_a, CT)["data"]["trip_id"] == T_A, r.reply_text)
    r = ra("haan", CT, trip=agent.TripInfo(title="Goa", start_date=None, end_date=None, id=T_GOA))
    check("confirm after the app opened ANOTHER trip -> refused, nothing added", r.error_code == "trip_changed"
          and len(expenses(T_A)) == n_a and len(expenses(T_GOA)) == 1, r.reply_text)
    with database.SessionLocal() as db:
        db.query(TripModel).filter(TripModel.id == T_GOA).first().user_id = uid_b   # Goa now belongs to someone else
        db.commit()
    ra("Goa trip mein auto 90", CT, [("tool", ("add_expense", {"title": "Auto", "amount": 90, "category": "transport", "trip_name": "Goa"}))])
    check("a trip that isn't the user's is never matched by name", P.get(redis_conn, uid_a, CT) is None)
    with database.SessionLocal() as db:
        db.query(TripModel).filter(TripModel.id == T_GOA).first().user_id = uid_a
        db.commit()
    ra("Goa trip mein auto 90", CT, [("tool", ("add_expense", {"title": "Auto", "amount": 90, "category": "transport", "trip_name": "Goa"}))])
    with database.SessionLocal() as db:
        db.query(TripModel).filter(TripModel.id == T_GOA).first().user_id = uid_b   # ownership changes before the confirm
        db.commit()
    r = ra("haan", CT)
    check("confirm re-checks ownership of the pending trip -> refused", r.action == "expense_failed" and len(expenses(T_GOA)) == 1)
    with database.SessionLocal() as db:
        db.query(TripModel).filter(TripModel.id == T_GOA).first().user_id = uid_a
        db.commit()
    r = ra("Goa trip ka plan dobara banao", CT, [("tool", ("regenerate_itinerary", {"trip_name": "Goa"}))])
    check("regenerate a named trip: the question names it", r.reply_text.startswith("Goa trip ka poora itinerary dobara banaun?")
          and P.get(redis_conn, uid_a, CT)["data"]["trip_id"] == T_GOA, r.reply_text)
    agent.cancel_pending(redis_conn, uid_a, CT, "hi")
    r = ra("Goa trip mein Fort Aguada ki jagah kuch aur", CT, [("tool", ("swap_activity", {"activity": "Fort Aguada", "trip_name": "Goa"}))])
    check("swap in a named trip: the sheet gets that trip's ID", r.ui_actions and r.ui_actions[0]["trip_id"] == T_GOA
          and r.ui_actions[0]["activity_id"] == ACT_G["Fort Aguada"])

    # ---------------- delete never deletes
    n = len(FakeTools.calls)
    r = ra("meri trip delete karo", CV)
    with database.SessionLocal() as db:
        still = db.query(TripModel).filter(TripModel.id == T_A).count() == 1
    check("'meri trip delete karo': fixed reply, opens /trip, no LLM call, trip still there",
          r.reply_text == "Trip delete karne ke liye button khud dabaiye, dhyan se." and r.ui_actions == [{"type": "navigate", "to": "/trip"}]
          and len(FakeTools.calls) == n and still and r.action == "delete_refused")
    r = ra("is yatra ko khatam kar do", CV, [("text", "Trip delete karne ke liye button khud dabaiye, dhyan se.")])
    check("the model refusing in words -> same reply + open /trip", r.action == "delete_refused" and types(r) == ["navigate"])
    check("no delete tool is offered", not any("delete" in n_ for n_ in agent.TOOL_NAMES))

log = buf.getvalue()
logging.getLogger("voice").removeHandler(handler)
check("log: action names + timings", "action=mark_done" in log and "action=expense_added" in log and "llm_ms=" in log, log[-300:])
check("log: no words, amounts or place names", not any(w in log for w in ("Hawa", "Amber", "Auto", "350", "1200", "Khana", "City Palace")), log)


# ---------------- socket: the Confirm / Cancel buttons for an expense
def pcm(seconds):
    return b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 16000))) for i in range(int(16000 * seconds)))


class FakeSTT:
    text = "haan"

    def transcribe(self, audio):
        return STTResult(text=FakeSTT.text, language="hi", duration_ms=1000, latency_ms=50, provider="groq", model="w")


def recv_until(ws, kinds):
    while True:
        m_ = ws.receive_json()
        if m_.get("type") in kinds:
            return m_


def voice_turn(ws, conv, text):
    FakeSTT.text = text
    ws.send_json({"type": "start", "conversation_id": conv, "screen": "/trip", "trip_id": T_A})
    recv_until(ws, {"recording"})
    ws.send_bytes(pcm(0.5))
    ws.send_json({"type": "stop"})
    recv_until(ws, {"transcript"})
    return recv_until(ws, {"reply"})


with mock.patch.object(pipeline, "get_stt", lambda: FakeSTT()), mock.patch.object(groq_client, "groq_chat_tools", fake):
    with client.websocket_connect("/ws/voice", headers={"origin": "http://localhost:5173"}) as ws:
        ws.send_json({"type": "auth", "token": tok_a})
        recv_until(ws, {"ready"})
        CW = f"conv_s5w_{uuid.uuid4().hex[:6]}"
        before = len(expenses(T_A))
        FakeTools.queue = [("tool", ("add_expense", {"title": "Auto", "amount": 350, "category": "transport"}))]
        rep = voice_turn(ws, CW, "auto ka 350 add karo")
        pc = rep.get("pending_confirmation") or {}
        check("socket: the reply carries the expense Confirm card", pc.get("id") and pc.get("title") == "Add this expense?", pc)
        ws.send_json({"type": "confirm", "conversation_id": CW, "pending_id": pc.get("id")})
        cr = recv_until(ws, {"confirm_result"})
        check("socket: Confirm button adds it once + refresh", cr["ok"] and cr["ui_actions"] == [{"type": "refresh", "what": "expenses"}]
              and len(expenses(T_A)) == before + 1, cr)
        ws.send_json({"type": "confirm", "conversation_id": CW, "pending_id": pc.get("id")})
        check("socket: second Confirm does nothing", recv_until(ws, {"confirm_result"})["ok"] is False and len(expenses(T_A)) == before + 1)
        FakeTools.queue = [("tool", ("add_expense", {"title": "Auto", "amount": 90, "category": "transport"}))]
        pc = voice_turn(ws, CW, "auto ka 90")["pending_confirmation"]
        with client.websocket_connect("/ws/voice", headers={"origin": "http://localhost:5173"}) as wsb:
            wsb.send_json({"type": "auth", "token": tok_b})
            recv_until(wsb, {"ready"})
            FakeTools.queue = [("text", "Kya?")]
            FakeSTT.text = "kuch bhi"
            wsb.send_json({"type": "start", "conversation_id": CW, "screen": "/trip"})
            recv_until(wsb, {"recording"})
            wsb.send_bytes(pcm(0.5))
            wsb.send_json({"type": "stop"})
            recv_until(wsb, {"reply"})
            wsb.send_json({"type": "confirm", "conversation_id": CW, "pending_id": pc["id"]})
            check("socket: another user can't confirm A's expense", recv_until(wsb, {"confirm_result"})["ok"] is False
                  and len(expenses(T_A)) == before + 1)
        ws.send_json({"type": "cancel", "conversation_id": CW, "pending_id": pc["id"]})
        cr = recv_until(ws, {"confirm_result"})
        check("socket: Cancel -> nothing added", cr["ok"] and len(expenses(T_A)) == before + 1 and P.get(redis_conn, uid_a, CW) is None)
client.__exit__(None, None, None)

print(f"\ntimings (code only, SQLite + local Redis, LLM simulated): small action {small_ms:.0f} ms, big action (pending + confirm) {big_ms:.0f} ms")
for prefix in ("voice:mem", "voice:pending", "voice:draft", "voice:confirm", "voice:lastplace"):
    for u in (uid_a, uid_b):
        for key in redis_conn.scan_iter(f"{prefix}:{u}:*"):
            redis_conn.delete(key)
for u in (uid_a, uid_b):
    redis_conn.delete(f"rl:ws:ai_trip:{u}")
print(f"\n{sum(results)}/{len(results)} passed", flush=True)
sys.exit(0 if all(results) else 1)
