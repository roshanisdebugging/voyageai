"""
Step 6 eval (voicefirst.md): smart actions by voice. 22 real phrases (Hinglish, English, Hindi/Tamil/Bengali script),
graded on the agent's DECISION with the REAL OpenAI API: the same prompt and tools as voice/agent.py, with a trip open,
then the tool chosen and the values it extracted (days checked against today's India date). Tools are not run:
the forecast, the AI suggestions and the database are never touched (the services are simulated in the unit tests).
Includes a few earlier-step phrases (a weather QUESTION, a tour-guide question) to catch regressions.
Paced ~4.5 s per call (the account's per-minute token limit), retried after 20 s on a rate limit.

Run from backend/: python -m scripts.eval_smart
"""
import sys
import time
from datetime import timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env", override=True)

from openai_client import LLMRateLimited, chat_tools  # noqa: E402
from trip_lifecycle import today_ist  # noqa: E402
from voice import agent  # noqa: E402

PACE_SECONDS = 4.5
TODAY = today_ist()
d = lambda n: (TODAY + timedelta(days=n)).isoformat()  # noqa: E731
TRIP = agent.TripInfo(title="Jaipur trip", start_date=d(0), end_date=d(3), id="trip_eval")


def low(v):
    return str(v or "").lower()


def day_is(*accepted):
    """The model's `day` (language-neutral) must be one of these; None counts when None is listed."""
    return lambda a: (a.get("day") if a.get("day") not in ("", "null") else None) in accepted


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


ASKED_BUDGET = [{"role": "user", "content": "budget mein fit karo"},
                {"role": "assistant", "content": "Pehle budget batayein, kitna hai?"}]

# (phrase, history, expected tool, check(args) -> bool or None)
CASES = [
    ("Aaj baarish hai, plan badlo", [], "weather_replan", day_is(None, "today", "0", d(0))),
    ("kal ka plan mausam ke hisaab se karo", [], "weather_replan", day_is("tomorrow", d(1))),
    ("plan the day after tomorrow around the weather", [], "weather_replan", day_is("day_after_tomorrow", d(2))),
    ("baarish ki wajah se plan badal do", [], "weather_replan", None),
    ("change my plan because of the rain", [], "weather_replan", None),
    ("parso baarish hogi, indoor jagah rakh do", [], "weather_replan", day_is("day_after_tomorrow", d(2))),
    ("day 2 ka plan mausam ke hisaab se badlo", [], "weather_replan", day_is("2", d(1))),
    ("Aaj ka route chhota karo", [], "optimize_day", lambda a: day_is(None, "today", d(0))(a) and a.get("goal") in (None, "MINIMIZE_TRAVEL_TIME")),
    ("day 2 optimize karo", [], "optimize_day", day_is("2", d(1))),
    ("make day 3 more relaxed", [], "optimize_day", lambda a: day_is("3", d(2))(a) and a.get("goal") == "RELAXED"),
    ("doosre din mein zyada jagahein dikhao", [], "optimize_day", lambda a: a.get("goal") == "MORE_SIGHTS"),
    ("optimize my route for tomorrow", [], "optimize_day", day_is("tomorrow", d(1))),
    ("day 2 ka order badal do", [], "optimize_day", day_is("2", d(1))),
    ("budget mein fit karo", [], "optimize_budget", lambda a: a.get("budget_inr") in (None, "", "null")),
    ("kharcha kam karo", [], "optimize_budget", lambda a: a.get("budget_inr") in (None, "", "null")),
    ("make the plan fit my budget", [], "optimize_budget", lambda a: a.get("budget_inr") in (None, "", "null")),
    ("50 hazaar", ASKED_BUDGET, "optimize_budget", lambda a: num(a.get("budget_inr")) == 50000),
    # regressions: a weather QUESTION and a tour-guide question must not become replans
    ("kal baarish hogi kya?", [], "get_weather", None),
    ("Hawa Mahal kab khulta hai", [], "answer_question", None),
    # other scripts: the values are still language-neutral
    ("நாளை மழை பெய்கிறது, திட்டத்தை மாற்று", [], "weather_replan", day_is("tomorrow", d(1))),
    ("আজকের রুট ছোট করো", [], "optimize_day", day_is(None, "today", d(0))),
    ("बजट के अंदर प्लान करो", [], "optimize_budget", None),
]


def decide(phrase, history):
    msgs = [{"role": "system", "content": agent.build_system_prompt("/trip/itinerary", TRIP)}, *history,
            {"role": "user", "content": phrase}]
    for attempt in range(4):
        t = time.perf_counter()
        try:
            out = chat_tools(msgs, agent.TOOLS, tool_choice="auto", temperature=0.2, timeout=agent.LLM_TIMEOUT_SECONDS,
                             reasoning_effort="low")
            return out, int((time.perf_counter() - t) * 1000)
        except LLMRateLimited:
            if attempt == 3:
                raise
            time.sleep(20)


def main():
    rows = []
    for i, (phrase, history, tool, chk) in enumerate(CASES):
        if i:
            time.sleep(PACE_SECONDS)
        try:
            out, ms = decide(phrase, history)
            call = next((c for c in out["tool_calls"] if c.get("name") in agent.TOOL_NAMES), None)
            args = (call or {}).get("arguments") or {}
            ok = bool(call and call["name"] == tool and (chk is None or chk(args)))
            got = f"{call['name']} {args}" if call else f"no tool: {(out.get('content') or '')[:60]}"
        except Exception as err:
            ok, got, ms = False, f"error {type(err).__name__}", 0
        rows.append((phrase + (" [history]" if history else ""), tool, ok, ms, got))
    w = max(len(r[0]) for r in rows)
    print(f"{'phrase':<{w}} | {'expected':<16} | ok | llm_ms | got")
    print("-" * (w + 110))
    for phrase, tool, ok, ms, got in rows:
        print(f"{phrase:<{w}} | {tool:<16} | {'OK' if ok else 'XX'} | {ms:>6} | {got[:110]}")
    good = sum(r[2] for r in rows)
    ms_list = sorted(r[3] for r in rows if r[3])
    print(f"\nsmart-action phrases: {good}/{len(rows)} = {100 * good / len(rows):.0f}%   (target >= 90%)")
    if ms_list:
        print(f"llm_ms: avg {sum(ms_list) / len(ms_list):.0f}, median {ms_list[len(ms_list) // 2]}, max {max(ms_list)}")


if __name__ == "__main__":
    main()
