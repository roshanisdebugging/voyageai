"""
Trip budget: voice set_trip_budget (asks first, then saves) and the itinerary page's "Set budget"
(/ws/app trips:set_budget + REST PUT /api/trips/{id}/budget). App DB = SQLite, Redis = local, OpenAI simulated.
Checks: the confirm card text, nothing saved before "haan" / Confirm, saved once after, the budget level follows the
amount, out-of-range amounts refused with the existing budget_out_of_range reply, same amount, no trip open, a trip
being planned by voice (the amount goes to the draft), another user's trip, cancel, the prompt rule, and the
ui actions that refresh the itinerary page.
Run from backend/: python -m tests.test_voice_budget
"""
import json
import os
import sys
import tempfile
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
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'budget.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
import openai_client  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from models_trip import TripModel  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from trip_lifecycle import MAX_BUDGET_INR, MIN_BUDGET_INR, budget_level_for, today_ist  # noqa: E402
from voice import agent, draft as D, pending as P  # noqa: E402
from voice.tools import smart  # noqa: E402

main.SessionLocal = database.SessionLocal
database.Base.metadata.create_all(bind=database.engine)
for key in redis_conn.scan_iter("rl:*"):
    redis_conn.delete(key)

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


TODAY = today_ist()
USER = f"usr_bg_{uuid.uuid4().hex[:8]}"
OTHER = f"usr_bg_other_{uuid.uuid4().hex[:8]}"


def add_trip(user, budget=None, days=3, adults=2, children=0):
    tid = f"trip_{uuid.uuid4().hex[:10]}"
    travelers = [{"id": f"tr_{i}", "type": "ADULT"} for i in range(adults)] + [{"id": f"c_{i}", "type": "CHILD"} for i in range(children)]
    with database.SessionLocal() as db:
        db.add(TripModel(id=tid, user_id=user, title="Jaipur Trip", status="PLANNING",
                         start_date=(TODAY + timedelta(days=1)).isoformat(), end_date=(TODAY + timedelta(days=days)).isoformat(),
                         total_days=days, destination_json=json.dumps({"name": "Jaipur", "latitude": 26.91, "longitude": 75.79}),
                         travelers_json=json.dumps(travelers),
                         budget_json=json.dumps({"level": "MODERATE", "targetAmount": budget, "currency": "INR"} if budget else {"level": "MODERATE"}),
                         created_at="2026-11-01", updated_at="2026-11-01"))
        db.commit()
    return tid


def budget_of(tid):
    with database.SessionLocal() as db:
        return dict(db.query(TripModel).filter(TripModel.id == tid).first().budget or {})


class FakeLLM:
    queue = []
    prompts = []

    def __call__(self, messages, tools, **kw):
        FakeLLM.prompts.append(messages[0]["content"])
        name, args = FakeLLM.queue.pop(0)
        return {"content": None, "tool_calls": [{"name": name, "arguments": args}]}


def say(text, args, *, trip_id=None, conv, lang="hi", tool="set_trip_budget"):
    FakeLLM.queue = [(tool, args)]
    trip = agent.TripInfo(title="Jaipur Trip", start_date=None, end_date=None, id=trip_id) if trip_id else None
    return agent.run_agent(text, lang, user_id=USER, conversation_id=conv, screen="/trip/itinerary", trip=trip,
                           redis_conn=redis_conn)


def conv():
    return f"conv_bg_{uuid.uuid4().hex[:6]}"


with mock.patch.object(openai_client, "chat_tools", FakeLLM()):
    # ---------------- the tool and the prompt rule
    check("set_trip_budget offered", "set_trip_budget" in agent.TOOL_NAMES)
    schema = next(t for t in agent.TOOLS if t["function"]["name"] == "set_trip_budget")["function"]["parameters"]
    check("set_trip_budget: amount (number) required", schema["required"] == ["amount"]
          and schema["properties"]["amount"]["type"] == "number")
    prompt = agent.build_system_prompt("/trip/itinerary", agent.TripInfo("Jaipur Trip", None, None, id="t"))
    check("prompt: open trip + budget amount -> set_trip_budget, never update_trip_draft",
          "a budget amount is ALWAYS set_trip_budget, NEVER update_trip_draft" in " ".join(prompt.split())
          and "budget badal ke 40 hazaar" in prompt)

    # ---------------- change an existing budget: asks, then saves once
    tid = add_trip(USER, budget=25000)
    c = conv()
    r = say("budget badal ke 40 hazaar rakho", {"amount": 40000}, trip_id=tid, conv=c)
    pc = r.pending_confirmation or {}
    check("asks first: 'Trip ka budget ₹25,000 se ₹40,000 kar doon?'",
          r.action == "smart_ask" and pc.get("summary") == "Trip ka budget ₹25,000 se ₹40,000 kar doon?", (r.action, pc))
    check("nothing saved before the confirm", budget_of(tid).get("targetAmount") == 25000)
    r2 = agent.confirm_pending(redis_conn, USER, c, "hi", pc.get("id"), tid)
    b = budget_of(tid)
    check("Confirm -> saved, 'Ho gaya, budget ab ₹40,000 hai.'", r2.action == "smart_applied" and b.get("targetAmount") == 40000
          and r2.reply_text == "Ho gaya, budget ab ₹40,000 hai.", (r2.action, r2.reply_text, b))
    check("the budget level follows the amount (2 adults, 3 days)", b.get("level") == budget_level_for(40000, 3, 2, 0), b)
    check("confirm result refreshes the itinerary page and opens it",
          r2.ui_actions[0] == {"type": "refresh", "what": "itinerary"} and r2.ui_actions[1]["type"] == "navigate"
          and r2.ui_actions[1]["to"].startswith("/trip"), r2.ui_actions)
    again = agent.confirm_pending(redis_conn, USER, c, "hi", pc.get("id"), tid)
    check("a second confirm does nothing", again.error_code == "no_pending" and budget_of(tid).get("targetAmount") == 40000)

    # voice "haan" works the same as the Confirm button
    c = conv()
    r = say("budget 25000 kar do", {"amount": 25000}, trip_id=tid, conv=c)
    FakeLLM.queue = []
    r2 = agent.run_agent("haan", "hi", user_id=USER, conversation_id=c, screen="/trip/itinerary",
                         trip=agent.TripInfo("Jaipur Trip", None, None, id=tid), redis_conn=redis_conn)
    check("'haan' confirms (no LLM call), budget saved", r2.action == "smart_applied" and budget_of(tid).get("targetAmount") == 25000
          and FakeLLM.queue == [], r2.action)

    # ---------------- a trip with no budget: "rakh doon?"
    t_none = add_trip(USER)
    r = say("set budget to 30000", {"amount": 30000}, trip_id=t_none, conv=conv(), lang="en")
    check("no budget yet (English): 'Set the trip budget to ₹30,000?'",
          (r.pending_confirmation or {}).get("summary") == "Set the trip budget to ₹30,000?", r.pending_confirmation)
    r = say("trip ka budget tees hazaar rakh do", {"amount": 30000}, trip_id=t_none, conv=conv())
    check("no budget yet (Hinglish): 'Trip ka budget ₹30,000 rakh doon?'",
          (r.pending_confirmation or {}).get("summary") == "Trip ka budget ₹30,000 rakh doon?", r.pending_confirmation)

    # ---------------- out of range, same amount, missing amount
    c = conv()
    r = say("budget 500 kar do", {"amount": 500}, trip_id=tid, conv=c)
    check("below the minimum -> the existing budget_low reply, code budget_out_of_range, nothing pending",
          r.error_code == "budget_out_of_range" and r.reply_text == smart._t("budget_low", "hi", min=f"{MIN_BUDGET_INR:,}", max="")
          and r.pending_confirmation is None and P.get(redis_conn, USER, c) is None, r.reply_text)
    r = say("budget 2 crore kar do", {"amount": 20_000_000}, trip_id=tid, conv=c)
    check("above the maximum -> budget_high", r.error_code == "budget_out_of_range"
          and r.reply_text == smart._t("budget_high", "hi", min="", max=f"{MAX_BUDGET_INR:,}"), r.reply_text)
    r = say("budget 25000 kar do", {"amount": 25000}, trip_id=tid, conv=conv())
    check("same amount -> 'Budget pehle se ₹25,000 hai.', nothing pending",
          r.reply_text == "Budget pehle se ₹25,000 hai." and r.pending_confirmation is None, r.reply_text)
    r = say("budget badlo", {"amount": None}, trip_id=tid, conv=conv())
    check("no amount -> asks 'Kitna budget rakhun?'", r.reply_text == "Kitna budget rakhun?", r.reply_text)

    # ---------------- cancel
    c = conv()
    r = say("budget 60000 kar do", {"amount": 60000}, trip_id=tid, conv=c)
    cancel = agent.cancel_pending(redis_conn, USER, c, "hi")
    check("Cancel -> nothing changed", cancel.action == "smart_cancel" and budget_of(tid).get("targetAmount") == 25000
          and P.get(redis_conn, USER, c) is None, cancel.action)

    # ---------------- no trip open / a trip being planned / another user's trip
    r = say("budget 40000 kar do", {"amount": 40000}, conv=conv())
    check("no trip open, nothing being planned -> 'Pehle koi trip kholiye.'", r.reply_text == smart.TEXT["no_trip"]["hi"]
          and r.error_code == "no_trip", r.reply_text)
    c = conv()
    d = D.TripDraftState()
    if d is not None:
        d.destination = {"name": "Goa", "country": "India", "latitude": 15.29, "longitude": 74.12}
        D.save(redis_conn, USER, c, d)
        r = say("budget 50 hazaar kar do", {"amount": 50000}, conv=c)
        saved = D.load(redis_conn, USER, c)
        check("no trip open but a new trip being planned -> the amount goes to the draft (update_trip_draft)",
              r.action.startswith("trip_") and saved is not None and saved.budget_inr == 50000, (r.action, getattr(saved, "budget_inr", None)))
        D.delete(redis_conn, USER, c)
    else:
        check("draft class available for the planning check", False, "voice.draft has no Draft")
    t_other = add_trip(OTHER, budget=10000)
    r = say("budget 40000 kar do", {"amount": 40000}, trip_id=t_other, conv=conv())
    check("another user's trip -> not found, never changed", r.error_code == "not_found" and budget_of(t_other).get("targetAmount") == 10000)

# ---------------- the itinerary page's "Set budget": WS trips:set_budget and REST
client = TestClient(main.app)
client.__enter__()


def register(name):
    r = client.post("/api/auth/register", json={"name": name, "email": f"bg_{uuid.uuid4().hex[:6]}@example.com", "password": "secret123"})
    assert r.status_code == 200, r.text
    return r.json()["token"], r.json()["authUser"]["id"]


tok_a, uid_a = register("Budget A")
tok_b, uid_b = register("Budget B")
client.cookies.clear()
t_a = add_trip(uid_a)
with client.websocket_connect("/ws/app") as ws:
    def call(action, payload, token):
        ws.send_json({"id": "b", "action": action, "payload": {**payload, "token": token}})
        while True:
            f = ws.receive_json()
            if f.get("id") == "b":
                return f

    f = call("trips:set_budget", {"trip_id": t_a, "amount": 25000}, tok_a)
    check("WS trips:set_budget saves and returns the trip", f["status"] == 200 and f["data"]["trip"]["budget"]["targetAmount"] == 25000
          and budget_of(t_a).get("targetAmount") == 25000, f.get("error"))
    f = call("trips:set_budget", {"trip_id": t_a, "amount": 500}, tok_a)
    check("WS: out of range -> 400 with the reason", f["status"] == 400 and "between" in (f.get("error") or ""), f)
    f = call("trips:set_budget", {"trip_id": t_a, "amount": 99999}, tok_b)
    check("WS: another user's trip -> 404, unchanged", f["status"] == 404 and budget_of(t_a).get("targetAmount") == 25000, f.get("status"))
r = client.put(f"/api/trips/{t_a}/budget", json={"amount": 30000}, headers={"Authorization": f"Bearer {tok_a}"})
check("REST PUT /api/trips/{id}/budget saves", r.status_code == 200 and budget_of(t_a).get("targetAmount") == 30000, r.text[:200])
r = client.put(f"/api/trips/{t_a}/budget", json={"amount": "abc"}, headers={"Authorization": f"Bearer {tok_a}"})
check("REST: not a number -> 400", r.status_code == 400, r.status_code)
r = client.put(f"/api/trips/{t_a}/budget", json={"amount": 40000}, headers={"Authorization": f"Bearer {tok_b}"})
check("REST: another user's trip -> 404, unchanged", r.status_code == 404 and budget_of(t_a).get("targetAmount") == 30000, r.status_code)
client.__exit__(None, None, None)

for k in list(redis_conn.scan_iter(f"voice:*{USER}*")) + list(redis_conn.scan_iter("rl:*")):
    redis_conn.delete(k)
print(f"\n{sum(results)}/{len(results)} passed", flush=True)
sys.exit(0 if all(results) else 1)
