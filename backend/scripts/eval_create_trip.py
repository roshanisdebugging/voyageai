"""
Step 4 eval (voicefirst.md): create a trip by voice. 15 real phrases (Hinglish and English), graded on the agent's
DECISION with the REAL Groq API: the same prompt and tools as voice/agent.py, then the tool chosen and the values
it extracted (dates checked against today's India date). Tools are not run: nothing is saved, no place search.
Phrases said while a trip is being planned get that draft in the prompt, as in the app.
Paced ~4.5 s per call (Groq's per-minute token allowance), retried after 20 s on a rate limit.

Run from backend/: python -m scripts.eval_create_trip
"""
import sys
import time
from datetime import date, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env", override=True)

from groq_client import GroqRateLimited, groq_chat_tools  # noqa: E402
from trip_lifecycle import today_ist  # noqa: E402
from voice import agent, draft as D  # noqa: E402

PACE_SECONDS = 4.5
TODAY = today_ist()


def next_date(month: int, day: int) -> str:
    """The next occurrence of day/month on or after today."""
    d = date(TODAY.year, month, day)
    return (d if d >= TODAY else date(TODAY.year + 1, month, day)).isoformat()


GOA_DRAFT = D.TripDraftState(destination={"name": "Goa"}, start_date=next_date(12, 15), end_date=next_date(12, 18), adults=2)


def low(v):
    return str(v or "").lower()


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# (phrase, lang, draft in progress or None, expected tool, check(args) -> bool)
CASES = [
    ("Goa jaana hai, 15 se 18 December, do log", "hi", None, "update_trip_draft",
     lambda a: "goa" in low(a.get("destination")) and a.get("start_date") == next_date(12, 15)
     and a.get("end_date") == next_date(12, 18) and num(a.get("adults")) == 2),
    ("trip banao Jaipur ke liye", "hi", None, "update_trip_draft", lambda a: "jaipur" in low(a.get("destination"))),
    ("nahi, budget 50 hazaar kar do", "hi", GOA_DRAFT, "update_trip_draft", lambda a: num(a.get("budget_inr")) == 50000),
    ("Delhi se Jaipur jaana hai 3 din ke liye, budget 20 hazaar", "hi", None, "update_trip_draft",
     lambda a: "jaipur" in low(a.get("destination")) and "delhi" in low(a.get("origin_city")) and num(a.get("days")) == 3
     and num(a.get("budget_inr")) == 20000),
    ("plan a trip to Udaipur from 5 to 8 January for 2 adults and 1 child", "en", None, "update_trip_draft",
     lambda a: "udaipur" in low(a.get("destination")) and a.get("start_date") == next_date(1, 5) and a.get("end_date") == next_date(1, 8)
     and num(a.get("adults")) == 2 and num(a.get("children")) == 1),
    ("I want to plan a trip to Manali", "en", None, "update_trip_draft", lambda a: "manali" in low(a.get("destination"))),
    ("budget 1.5 lakh hai", "hi", GOA_DRAFT, "update_trip_draft", lambda a: num(a.get("budget_inr")) == 150000),
    ("koi bachcha nahi, sirf hum do", "hi", GOA_DRAFT, "update_trip_draft",
     lambda a: num(a.get("children")) == 0 and (a.get("adults") is None or num(a.get("adults")) == 2)),
    ("20 December se 5 din", "hi", D.TripDraftState(destination={"name": "Goa"}, adults=2), "update_trip_draft",
     lambda a: a.get("start_date") == next_date(12, 20) and (num(a.get("days")) == 5
                                                                or a.get("end_date") == (date.fromisoformat(next_date(12, 20)) + timedelta(days=4)).isoformat())),
    ("Mumbai se jaayenge", "hi", GOA_DRAFT, "update_trip_draft", lambda a: "mumbai" in low(a.get("origin_city"))),
    ("cancel karo, trip nahi banani", "hi", GOA_DRAFT, "cancel_trip_draft", None),
    ("ek aur trip banao Kerala ke liye", "hi", GOA_DRAFT, "update_trip_draft",
     lambda a: "kerala" in low(a.get("destination")) and a.get("start_new") is True),
    ("make it 3 adults", "en", GOA_DRAFT, "update_trip_draft", lambda a: num(a.get("adults")) == 3),
    ("Rishikesh ki trip plan karni hai, 25000 budget", "hi", None, "update_trip_draft",
     lambda a: "rishikesh" in low(a.get("destination")) and num(a.get("budget_inr")) == 25000),
    ("nayi trip banani hai", "hi", None, "navigate", lambda a: a.get("page") == "plan_trip"),
]


def decide(phrase, draft):
    msgs = [{"role": "system", "content": agent.build_system_prompt("/home", None, draft_line=agent._draft_line(draft))},
            {"role": "user", "content": phrase}]
    for attempt in range(4):
        t = time.perf_counter()
        try:
            out = groq_chat_tools(msgs, agent.TOOLS, tool_choice="auto", temperature=0.2, timeout=agent.LLM_TIMEOUT_SECONDS,
                                  reasoning_effort="low")
            return out, int((time.perf_counter() - t) * 1000)
        except GroqRateLimited:
            if attempt == 3:
                raise
            time.sleep(20)


def main():
    rows = []
    for i, (phrase, lang, draft, tool, chk) in enumerate(CASES):
        if i:
            time.sleep(PACE_SECONDS)
        try:
            out, ms = decide(phrase, draft)
            call = next((c for c in out["tool_calls"] if c.get("name") in agent.TOOL_NAMES), None)
            args = (call or {}).get("arguments") or {}
            ok = bool(call and call["name"] == tool and (chk is None or chk(args)))
            got = f"{call['name']} {args}" if call else f"no tool: {(out.get('content') or '')[:60]}"
        except Exception as err:
            ok, got, ms = False, f"error {type(err).__name__}", 0
        rows.append((phrase + (" [draft]" if draft else ""), tool, ok, ms, got))
    w = max(len(r[0]) for r in rows)
    print(f"{'phrase':<{w}} | {'expected':<18} | ok | llm_ms | got")
    print("-" * (w + 110))
    for phrase, tool, ok, ms, got in rows:
        print(f"{phrase:<{w}} | {tool:<18} | {'✓' if ok else '✗'}  | {ms:>6} | {got[:110]}")
    good = sum(r[2] for r in rows)
    ms_list = sorted(r[3] for r in rows if r[3])
    print(f"\ncreate-trip phrases: {good}/{len(rows)} = {100 * good / len(rows):.0f}%   (target >= 90%)")
    if ms_list:
        print(f"llm_ms: avg {sum(ms_list) / len(ms_list):.0f}, median {ms_list[len(ms_list) // 2]}, max {max(ms_list)}")


if __name__ == "__main__":
    main()
