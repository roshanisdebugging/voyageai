"""
Navigation eval for the voice agent (voicefirst.md step 2).

Runs typed phrases through voice/agent.py with the REAL Groq API (no STT, no TTS) and prints
phrase | expected | got | ok, plus total accuracy. Target >= 90%.
Uses real Groq requests: run it once per change, not in a loop. Calls are paced (~2.2 s apart)
because Groq's free tier allows 30 requests a minute for the whole account.

Run from backend/: python -m scripts.eval_navigation
"""
import sys
import time
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env", override=True)

from redis_client import redis_conn  # noqa: E402
from voice import agent  # noqa: E402

TRIP = agent.TripInfo(title="Jaipur Tour Package", start_date="2027-01-10", end_date="2027-01-12")

# (phrase, stt language, expected, trip open?)
# expected: a route ("/map", "/trip/itinerary?day=2"), "NONE" (no navigation) or "QUESTION" (no navigation, asks back)
CASES = [
    ("map dikha", "hi", "/map", True),
    ("map kholo", "hi", "/map", True),
    ("itinerary pe le chalo", "hi", "/trip/itinerary", True),
    ("day 2 dikhao", "hi", "/trip/itinerary?day=2", True),
    ("doosre din ka plan", "hi", "/trip/itinerary?day=2", True),
    ("show me day three", "en", "/trip/itinerary?day=3", True),
    ("teesre din ka itinerary dikhao", "hi", "/trip/itinerary?day=3", True),
    ("kharche dikhao", "hi", "/expenses", True),
    ("expenses kholo", "hi", "/expenses", True),
    ("show my expenses", "en", "/expenses", True),
    ("cab chahiye", "hi", "/rides", True),
    ("book a ride", "en", "/rides", True),
    ("khana dikhao", "hi", "/food", True),
    ("where can I eat", "en", "/food", True),
    ("ghoomne ki jagah dikhao", "hi", "/explore", True),
    ("explore kholo", "hi", "/explore", True),
    ("tour guide kholo", "hi", "/guide", True),
    ("guide se baat karni hai", "hi", "/guide", True),
    ("meri trips dikhao", "hi", "/trips", True),
    ("home pe le chalo", "hi", "/home", True),
    ("go home", "en", "/home", True),
    ("saved places", "en", "/saved-places", True),
    ("open saved places", "en", "/saved-places", True),
    ("settings kholo", "hi", "/more", True),
    ("nayi trip banani hai", "hi", "/trips/new", True),
    ("plan a new trip", "en", "/trips/new", True),
    ("open my itinerary", "en", "/trip/itinerary", True),
    ("take me to the map", "en", "/map", True),
    ("ek joke sunao", "hi", "NONE", True),
    ("cricket score kya hai", "hi", "NONE", True),
    ("woh wala kholo", "hi", "QUESTION", True),
    ("itinerary kholo", "hi", "/trips", False),  # no trip open -> my trips
]


def grade(expected, result):
    routes = [a.get("to") for a in result.ui_actions if a.get("type") == "navigate"]
    if expected == "NONE":
        return not routes, "no navigation" if not routes else routes[0]
    if expected == "QUESTION":
        asked = not routes and result.reply_text.strip().endswith("?")
        return asked, ("asked: " + result.reply_text) if not routes else routes[0]
    got = routes[0] if routes else f"(none: {result.action}{'/' + result.error_code if result.error_code else ''})"
    return got == expected, got


def main():
    run_id = uuid.uuid4().hex[:8]
    user = f"eval_{run_id}"
    rows, ok_count, llm = [], 0, []
    for i, (phrase, lang, expected, has_trip) in enumerate(CASES):
        if i:
            time.sleep(2.2)  # stay under Groq's 30 requests/minute
        conv = f"eval_{run_id}_{i}"  # fresh conversation per phrase: no memory carry-over
        res = agent.run_agent(phrase, lang, user_id=user, conversation_id=conv, screen="/home",
                              trip=TRIP if has_trip else None, redis_conn=redis_conn)
        ok, got = grade(expected, res)
        ok_count += ok
        llm.append(res.llm_ms)
        rows.append((phrase + ("" if has_trip else "  [no trip]"), expected, got, "✓" if ok else "✗", res.reply_text, res.llm_ms))
    for key in redis_conn.scan_iter(f"voice:mem:{user}:*"):
        redis_conn.delete(key)

    w = max(len(r[0]) for r in rows)
    print(f"{'phrase':<{w}} | {'expected':<22} | {'got':<30} | ok | llm_ms | reply")
    print("-" * (w + 100))
    for phrase, exp, got, mark, reply, ms in rows:
        print(f"{phrase:<{w}} | {exp:<22} | {got[:30]:<30} | {mark}  | {ms:>6} | {reply}")
    acc = 100 * ok_count / len(rows)
    print(f"\naccuracy: {ok_count}/{len(rows)} = {acc:.0f}%   (target >= 90%)")
    print(f"llm_ms: avg {sum(llm) / len(llm):.0f}, max {max(llm)}")


if __name__ == "__main__":
    main()
