"""
Step 5 eval (voicefirst.md): actions by voice. ~30 action phrases plus a sample of step 2, 3 and 4 phrases (to check
nothing regressed), graded on the agent's DECISION with the REAL OpenAI API: the same prompt (with an open Jaipur trip's
plan) and tools as voice/agent.py, then the tool chosen and its values. For activity names, the CODE match
(voice/context.match_activity) must land on the right activity. Tools are not run: nothing is saved.
Delete phrases are answered by code before any LLM call (agent.is_delete_request); those count when code catches them.

Each call is ~2,900 tokens; calls are paced ~22 s apart to stay under a per-minute token limit.
Run from backend/: python -m scripts.eval_actions
"""
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env", override=True)

from openai_client import LLMRateLimited, chat_tools  # noqa: E402
from trip_lifecycle import today_ist  # noqa: E402
from voice import agent, context as C  # noqa: E402

PACE_SECONDS = 22
TODAY = today_ist()
TOMORROW = TODAY.fromordinal(TODAY.toordinal() + 1)

ACTS = [("a1", "Visit Hawa Mahal", 1), ("a2", "Amber Fort", 1), ("a3", "Lunch at LMB", 1), ("a4", "Jal Mahal", 1),
        ("a5", "City Palace", 2), ("a6", "Nahargarh Fort", 2), ("a7", "Chokhi Dhani dinner", 2)]
CTX = C.TripContext(trip_id="trip_eval", title="Jaipur Getaway", destination="Jaipur",
                    activities=[C.Act(s, f"id_{s}", t, n, (TODAY if n == 1 else TOMORROW).isoformat(), False) for s, t, n in ACTS],
                    days=[(1, TODAY.isoformat()), (2, TOMORROW.isoformat())], spent=1500, budget=20000, today_day=1,
                    itinerary_status="READY")
TRIP = agent.TripInfo(title="Jaipur Getaway", start_date=TODAY.isoformat(), end_date=TOMORROW.isoformat(), id="trip_eval")


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def act(short, done=True):
    """The code match of the model's activity argument must be this activity (and done as expected)."""
    def chk(a):
        hit, _ = C.match_activity(CTX, a.get("activity"))
        return hit is not None and hit.short == short and ((a.get("done") is not False) == done)
    return chk


def expense(amount, cats):
    return lambda a: num(a.get("amount")) == amount and (a.get("category") or "other") in cats


def no_wrong_match(a):
    hit, _ = C.match_activity(CTX, a.get("activity"))
    return hit is None


S = "/trip"
# (phrase, screen, expected tool | "code_delete" | "refuse" | "ask", check(args) or None, group)
CASES = [
    # --- step 5: small actions
    ("Hawa Mahal done ho gaya", S, "mark_activity_done", act("a1"), "s5"),
    ("Amber Fort ho gaya", S, "mark_activity_done", act("a2"), "s5"),
    ("City Palace dekh liya", S, "mark_activity_done", act("a5"), "s5"),
    ("mark Jal Mahal as done", S, "mark_activity_done", act("a4"), "s5"),
    ("Hawa Mahal abhi done nahi hua, wapas karo", S, "mark_activity_done", act("a1", done=False), "s5"),
    ("Hawa Mahal wala mark karo", S, "mark_activity_done", act("a1"), "s5"),
    ("lunch ho gaya", S, "mark_activity_done", act("a3"), "s5"),
    ("Chokhi Dhani ka dinner ho gaya", S, "mark_activity_done", act("a7"), "s5"),
    ("Taj Mahal done ho gaya", S, "ask", no_wrong_match, "s5"),
    ("yeh jagah save karo", "/details/ChIJx", "save_place", None, "s5"),
    ("Hawa Mahal save kar lo", S, "save_place", None, "s5"),
    ("save this place", "/details/ChIJx", "save_place", None, "s5"),
    ("Hawa Mahal saved se hatao", "/saved-places", "unsave_place", None, "s5"),
    ("remove this from my saved places", "/details/ChIJx", "unsave_place", None, "s5"),
    # --- step 5: big actions
    ("auto ka 350 add karo", S, "add_expense", expense(350, {"transport"}), "s5"),
    ("khane ka 1200 kharcha", S, "add_expense", expense(1200, {"food"}), "s5"),
    ("hotel ke liye 4500 diye", S, "add_expense", expense(4500, {"stay"}), "s5"),
    ("add 800 rupees for shopping", S, "add_expense", expense(800, {"shopping"}), "s5"),
    ("Amber Fort ke tickets 200 ke the", S, "add_expense", expense(200, {"tickets"}), "s5"),
    ("cab ka 600 likh do", S, "add_expense", expense(600, {"transport"}), "s5"),
    ("chai 40 rupaye", S, "add_expense", expense(40, {"food"}), "s5"),
    ("parking ka 50 add karo", S, "add_expense", expense(50, {"transport", "other"}), "s5"),
    ("Amber Fort ki jagah kuch aur", S, "swap_activity", act("a2"), "s5"),
    ("Nahargarh Fort ki jagah kuch aur dikhao", S, "swap_activity", act("a6"), "s5"),
    ("replace City Palace with something else", S, "swap_activity", act("a5"), "s5"),
    ("plan dobara banao", S, "regenerate_itinerary", None, "s5"),
    ("poora itinerary phir se banao", S, "regenerate_itinerary", None, "s5"),
    ("regenerate my itinerary", S, "regenerate_itinerary", None, "s5"),
    # --- step 5: which trip (a named trip vs the open one)
    ("Goa wali trip mein auto ka 350 add karo", S, "add_expense",
     lambda a: num(a.get("amount")) == 350 and "goa" in str(a.get("trip_name") or "").lower(), "s5"),
    ("December wali trip mein khane ka 500", S, "add_expense",
     lambda a: num(a.get("amount")) == 500 and "dec" in str(a.get("trip_month") or "").lower(), "s5"),
    ("agli trip ka plan dobara banao", S, "regenerate_itinerary", lambda a: a.get("trip_which") == "next", "s5"),
    ("auto ka 120 add karo", S, "add_expense",
     lambda a: num(a.get("amount")) == 120 and not (a.get("trip_name") or a.get("trip_month") or a.get("trip_which")), "s5"),
    # --- step 5: delete never deletes
    ("meri trip delete karo", S, "code_delete", None, "s5"),
    ("delete this trip", S, "code_delete", None, "s5"),
    ("itinerary mita do", S, "code_delete", None, "s5"),
    ("Amber Fort ko plan se nikaal do", S, "refuse", None, "s5"),
    # --- earlier steps (regression sample)
    ("itinerary kholo", S, "navigate", lambda a: a.get("page") == "itinerary", "s2"),
    ("expenses dikhao", S, "navigate", lambda a: a.get("page") == "expenses", "s2"),
    ("nayi trip banani hai", "/home", "navigate", lambda a: a.get("page") == "plan_trip", "s2"),
    ("Hawa Mahal kahan hai", S, "search_places", lambda a: a.get("show") is False, "s3"),
    ("Albert Hall dikhao", S, "search_places", lambda a: a.get("show") is True, "s3"),
    ("kal baarish hogi kya", S, "get_weather", None, "s3"),
    ("Amber Fort ki ticket kitne ki hai", S, "answer_question", None, "s3"),
    ("meri trips kaun si hain", S, "list_my_trips", None, "s3"),
    ("ek joke sunao", S, "cant_help", lambda a: a.get("reason") == "off_topic", "s3"),
    ("Goa jaana hai, 15 se 18 December, do log", "/home", "update_trip_draft", lambda a: "goa" in str(a.get("destination") or "").lower(), "s4"),
    ("Rishikesh ki trip plan karni hai, 25000 budget", "/home", "update_trip_draft", lambda a: num(a.get("budget_inr")) == 25000, "s4"),
]


def decide(phrase, screen):
    trip = TRIP if screen != "/home" else None
    msgs = [{"role": "system", "content": agent.build_system_prompt(
        screen, trip, trip_context=C.prompt_text(CTX) if trip else "none")}, {"role": "user", "content": phrase}]
    for attempt in range(4):
        t = time.perf_counter()
        try:
            out = chat_tools(msgs, agent.TOOLS, tool_choice="auto", temperature=0.2, timeout=agent.LLM_TIMEOUT_SECONDS,
                                  reasoning_effort="low")
            return out, int((time.perf_counter() - t) * 1000)
        except LLMRateLimited:
            if attempt == 3:
                raise
            time.sleep(30)


def grade(expected, chk, out):
    call = next((c for c in out["tool_calls"] if c.get("name") in agent.TOOL_NAMES), None)
    args = (call or {}).get("arguments") or {}
    got = f"{call['name']} {args}" if call else f"text: {(out.get('content') or '')[:70]}"
    if expected == "refuse":
        r = agent._decide(out["tool_calls"], out.get("content"), "hi", True)
        return r.action == "delete_refused" or (call is None and "delete" not in got.lower() and "?" in got), got
    if expected == "ask":
        if call and call["name"] == "mark_activity_done":
            return chk(args), got          # the code match must find nothing (it then asks)
        return call is None, got           # or the model asks itself
    return bool(call and call["name"] == expected and (chk is None or chk(args))), got


def main():
    rows = []
    first = True
    for phrase, screen, expected, chk, group in CASES:
        if expected == "code_delete":
            ok = agent.is_delete_request(phrase)
            rows.append((phrase, group, expected, ok, 0, "answered by code" if ok else "NOT caught by code"))
            continue
        if not first:
            time.sleep(PACE_SECONDS)
        first = False
        try:
            out, ms = decide(phrase, screen)
            ok, got = grade(expected, chk, out)
        except Exception as err:
            ok, got, ms = False, f"error {type(err).__name__}", 0
        rows.append((phrase, group, expected, ok, ms, got))
        print(f"{'✓' if ok else '✗'} {phrase} -> {got[:100]}", flush=True)
    w = max(len(r[0]) for r in rows)
    print(f"\n{'phrase':<{w}} | grp | {'expected':<20} | ok | llm_ms | got")
    print("-" * (w + 120))
    for phrase, group, expected, ok, ms, got in rows:
        print(f"{phrase:<{w}} | {group}  | {expected:<20} | {'✓' if ok else '✗'}  | {ms:>6} | {got[:100]}")
    for g in ("s5", "s2", "s3", "s4"):
        sub = [r for r in rows if r[1] == g]
        print(f"{g}: {sum(r[3] for r in sub)}/{len(sub)}")
    good = sum(r[3] for r in rows)
    print(f"\nall phrases: {good}/{len(rows)} = {100 * good / len(rows):.0f}%   (target >= 90%)")
    small = {"mark_activity_done", "save_place", "unsave_place"}
    big = {"add_expense", "swap_activity", "regenerate_itinerary"}
    for label, kinds in (("small actions", small), ("big actions", big), ("everything", None)):
        ms = sorted(r[4] for r in rows if r[4] and (kinds is None or r[2] in kinds))
        if ms:
            print(f"llm_ms {label}: avg {sum(ms) / len(ms):.0f}, median {ms[len(ms) // 2]}, max {max(ms)} (n={len(ms)})")


if __name__ == "__main__":
    main()
