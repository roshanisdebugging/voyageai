"""
Step 3 eval (voicefirst.md): questions and look-ups, plus step 2's navigation phrases.

Grades the agent's DECISION with the REAL OpenAI API: the same system prompt and tools as voice/agent.py,
then checks the tool chosen and its arguments. Tools are not run (no Gemini calls, nothing saved), so the
eval has no side effects. Calls are paced (~4.5 s, retry after 20 s on a rate limit) for the account's per-minute limits.

  python -m scripts.eval_lookups              # step 3 phrases + step 2 navigation phrases
  python -m scripts.eval_lookups --timings    # also time the real tools once (Gemini answers, Google search)
Run from backend/. Run once per change, not in a loop.
"""
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env", override=True)

from openai_client import chat_tools  # noqa: E402
from voice import agent, pages  # noqa: E402
from scripts.eval_navigation import CASES as NAV_CASES, TRIP  # noqa: E402

PACE_SECONDS = 4.5  # 5 tools make each call ~2k tokens: stay under the account's per-minute token limit

# (phrase, lang, expected, check, trip open?, history)
# expected: tool name, or "DECLINE" (no tool, no navigation) or "QUESTION" (no tool, asks back).
# check: for navigate the route; for others a function(args) -> bool (None = any args).
GOA_Q = [{"role": "user", "content": "Goa wali trip kholo"},
         {"role": "assistant", "content": "Goa ki 2 trips hain: November wali ya December wali?"}]


def has(*words):
    return lambda a: any(w.lower() in " ".join(str(v) for v in a.values()).lower() for w in words)


LOOKUP_CASES = [
    ("Amber Fort ki timing kya hai", "hi", "answer_question", has("amber"), True, None),
    ("Amber Fort kab jaana best hai", "hi", "answer_question", has("amber"), True, None),
    ("Jaipur mein kya khana famous hai", "hi", "answer_question", has("jaipur", "khana", "food"), True, None),
    ("Hawa Mahal ka ticket kitne ka hai", "hi", "answer_question", has("hawa"), True, None),
    ("what is the best time to visit Goa", "en", "answer_question", has("goa"), True, None),
    ("is Udaipur safe at night", "en", "answer_question", has("udaipur"), True, None),
    ("Delhi se Agra kaise jaayein", "hi", "answer_question", has("agra"), True, None),
    # "dikhao / show me" -> map now (show=true); "kahan hai / where is" -> say where, ask first (show=false)
    ("Hawa Mahal dikhao", "hi", "search_places", lambda a: has("hawa")(a) and a.get("show") is True, True, None),
    ("show me Gateway of India", "en", "search_places", lambda a: has("gateway")(a) and a.get("show") is True, True, None),
    ("India Gate map pe dikhao", "hi", "search_places", lambda a: has("india gate")(a) and a.get("show") is True, True, None),
    ("Amber Fort map par dikhao", "hi", "search_places", lambda a: has("amber")(a) and a.get("show") is True, True, None),
    ("Taj Mahal kahan hai", "hi", "search_places", lambda a: has("taj")(a) and a.get("show") is False, True, None),
    ("where is Amber Fort", "en", "search_places", lambda a: has("amber")(a) and a.get("show") is False, True, None),
    ("Qutub Minar kahan hai", "hi", "search_places", lambda a: has("qutub")(a) and a.get("show") is False, True, None),
    ("where is Charminar", "en", "search_places", lambda a: has("charminar")(a) and a.get("show") is False, True, None),
    # weather -> get_weather (never answer_question)
    ("kal Jaipur mein baarish hogi kya", "hi", "get_weather", lambda a: has("jaipur")(a) and str(a.get("day") or "").lower() in ("tomorrow", "kal"), True, None),
    ("aaj Goa ka mausam kaisa hai", "hi", "get_weather", has("goa"), True, None),
    ("will it rain in Mumbai tomorrow", "en", "get_weather", has("mumbai"), True, None),
    ("Shimla mein kitni thand hai", "hi", "get_weather", has("shimla"), True, None),
    ("what's the weather like today", "en", "get_weather", None, True, None),
    ("meri trips kaun si hain", "hi", "list_my_trips", lambda a: not a.get("include_past"), True, None),
    ("what trips do I have", "en", "list_my_trips", lambda a: not a.get("include_past"), True, None),
    ("meri purani trips batao", "hi", "list_my_trips", lambda a: a.get("include_past") is True, True, None),
    ("Goa wali trip kholo", "hi", "open_trip", has("goa"), True, None),
    ("open my Jaipur trip", "en", "open_trip", has("jaipur"), True, None),
    ("agli trip kholo", "hi", "open_trip", lambda a: a.get("which") == "next", True, None),
    ("pichli trip kholo", "hi", "open_trip", lambda a: a.get("which") == "last", True, None),
    ("December wali", "hi", "open_trip", lambda a: "dec" in str(a.get("month", "")).lower() or str(a.get("month")) == "12", True, GOA_Q),
    ("nayi trip banani hai", "hi", "navigate", "/trips/new", True, None),
    ("plan a new trip", "en", "navigate", "/trips/new", True, None),
    ("mujhe nayi trip plan karni hai", "hi", "navigate", "/trips/new", False, None),
    ("settings kholo", "hi", "navigate", "/more", True, None),
    ("open my profile", "en", "navigate", "/more", True, None),
    ("ek joke sunao", "hi", "DECLINE", None, True, None),
    ("who won the cricket match", "en", "DECLINE", None, True, None),
    ("write a python program", "en", "DECLINE", None, True, None),
    # garbled speech -> unclear (not "I only help with trips")
    ("blorf manta kizzle vopo", "en", "UNCLEAR", None, True, None),
    ("ka ka the trip sa no hmm", "hi", "UNCLEAR", None, True, None),
    ("zhrr pateeka lomnu", "hi", "UNCLEAR", None, True, None),
    ("woh wala dikhao", "hi", "QUESTION", None, True, None),
]


def decide(phrase, has_trip, history):
    msgs = [{"role": "system", "content": agent.build_system_prompt("/home", TRIP if has_trip else None)}]
    msgs += history or []
    msgs.append({"role": "user", "content": phrase})
    from openai_client import LLMRateLimited
    for attempt in range(4):
        t = time.perf_counter()
        try:
            out = chat_tools(msgs, agent.TOOLS, tool_choice="auto", temperature=0.2,
                             timeout=agent.LLM_TIMEOUT_SECONDS, reasoning_effort="low")
            return out, int((time.perf_counter() - t) * 1000)
        except LLMRateLimited:
            if attempt == 3:
                raise
            time.sleep(20)  # the account's per-minute limit; the eval waits, a user turn would not


def grade(expected, chk, out, has_trip):
    calls = [c for c in out["tool_calls"] if c.get("name") in agent.TOOL_NAMES]
    call = calls[0] if calls else None
    text = (out.get("content") or "").strip()
    reason = (call.get("arguments") or {}).get("reason") if call and call["name"] == "cant_help" else None
    if expected in ("DECLINE", "NONE"):
        ok = (call is None and expected == "NONE") or reason == "off_topic" or (call is None and "sirf" in text.lower() or "only help" in text.lower())
        if expected == "NONE":
            ok = ok or call is None or (call and call["name"] in ("answer_question", "cant_help"))
        return bool(ok), (f"{call['name']} {reason or ''}" if call else f"no tool: {text[:40]}")
    if expected == "UNCLEAR":
        return reason == "unclear", (f"{call['name']} {reason or (call.get('arguments') or {})}" if call else f"no tool: {text[:40]}")
    if expected == "QUESTION":
        return call is None and text.endswith("?"), (call["name"] if call else f"asked: {text[:40]}")
    if call is None:
        return False, f"no tool: {text[:40]}"
    args = call.get("arguments") or {}
    if expected == "navigate" or expected.startswith("/"):
        route = None
        if call["name"] == "navigate":
            route, err = pages.resolve(args.get("page"), args.get("day"), has_trip)
            route = route or ("/trips" if err == "no_trip" else None)
        elif call["name"] == "list_my_trips":
            route = "/trips"  # list_my_trips speaks the trips and opens My trips
        want = chk if expected == "navigate" else expected
        return route == want, f"{call['name']} {route or args}"
    ok = call["name"] == expected and (chk is None or bool(chk(args)))
    return ok, f"{call['name']} {args}"


def main():
    cases = [(p, l, e, c, t, h) for (p, l, e, c, t, h) in LOOKUP_CASES]
    cases += [(p, l, exp, None, t, None) for (p, l, exp, t) in NAV_CASES]
    rows, llm = [], []
    for i, (phrase, lang, expected, chk, has_trip, history) in enumerate(cases):
        if i:
            time.sleep(PACE_SECONDS)
        try:
            out, ms = decide(phrase, has_trip, history)
            ok, got = grade(expected, chk, out, has_trip)
        except Exception as err:
            ok, got, ms = False, f"error {type(err).__name__}", 0
        llm.append(ms)
        group = "step3" if i < len(LOOKUP_CASES) else "step2"
        rows.append((group, phrase + ("" if has_trip else " [no trip]"), expected if not str(expected).startswith("/") else expected, got, ok, ms))

    w = max(len(r[1]) for r in rows)
    print(f"{'set':<5} | {'phrase':<{w}} | {'expected':<16} | ok | llm_ms | got")
    print("-" * (w + 90))
    for group, phrase, exp, got, ok, ms in rows:
        print(f"{group:<5} | {phrase:<{w}} | {str(exp)[:16]:<16} | {'✓' if ok else '✗'}  | {ms:>6} | {got[:70]}")
    for group in ("step3", "step2"):
        sub = [r for r in rows if r[0] == group]
        good = sum(r[4] for r in sub)
        print(f"{group}: {good}/{len(sub)} = {100 * good / len(sub):.0f}%   (target >= 90%)")
    ok_llm = sorted(x for x in llm if x)
    print(f"llm_ms (deciding call): avg {sum(ok_llm) / len(ok_llm):.0f}, median {ok_llm[len(ok_llm) // 2]}, max {max(ok_llm)}")

    if "--timings" in sys.argv:
        import tour_guide_service as tgs
        from voice.tools import lookups
        print("\nTool timings (real; nothing saved):")
        for q, lang in [("Amber Fort ki timing kya hai", "hi"), ("Jaipur mein kya khana famous hai", "hi"),
                        ("What is the best time to visit Goa?", "en"), ("Hawa Mahal ka ticket kitne ka hai", "hi"),
                        ("Is Udaipur safe at night?", "en")]:
            t = time.perf_counter()
            ans = tgs.voice_answer(q, lang, user_id=None)
            print(f"  answer_question  {int((time.perf_counter() - t) * 1000):>5} ms  {ans['status']}/{ans['source']}  spoken: {ans['spoken']}")
            time.sleep(2.5)
        for q in ["Hawa Mahal", "Gateway of India", "Qutub Minar"]:
            t = time.perf_counter()
            r = lookups.search_place(q, "hi")
            print(f"  search_places    {int((time.perf_counter() - t) * 1000):>5} ms  {r.action}  {r.reply_text}")


if __name__ == "__main__":
    main()
