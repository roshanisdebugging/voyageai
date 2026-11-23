"""
Map stage 1 eval with the REAL Google key: 20 place searches through the shared search (places.search_places_detailed),
plus (with --voice) two spoken phrases through the real voice agent (OpenAI + Google).

    python -m scripts.eval_map_search [--fresh] [--voice]

Uses an in-memory cache, so every Google request is counted and nothing is written to Redis. --fresh clears it
before each search, so every search shows its uncached cost.
Up to 7 Google requests per search (1 autocomplete + up to 6 details). Never prints the key.
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

import places  # noqa: E402
from services import google_maps_service as gms  # noqa: E402
from voice.tools.lookups import city_state  # noqa: E402


class MemCache:
    def __init__(self):
        self.d = {}

    async def get(self, key):
        return self.d.get(key)

    async def set(self, key, value, ttl_seconds=0):
        self.d[key] = value


gms.cache = MemCache()

# The intended place: (lat, lng, km). A result is "intended" if it lies within km of it.
CHARMINAR = (17.3616, 78.4747, 1.5)
HAWA = (26.9239, 75.8267, 1.5)
AMER = (26.9855, 75.8513, 2.0)
TAJ = (27.1751, 78.0421, 2.0)
INDIA_GATE = (28.6129, 77.2295, 1.5)
GATEWAY = (18.9220, 72.8347, 1.5)
GOLDEN = (31.6200, 74.8765, 1.5)
GHATS = (25.3075, 83.0105, 3.5)
MARINE = (18.9440, 72.8230, 3.0)
QUTUB = (28.5245, 77.1855, 1.5)
CASES = [
    ("Charminar", CHARMINAR), ("4 minar", CHARMINAR), ("Hawa Mahal", HAWA), ("Amer Fort", AMER), ("Taj Mahal", TAJ),
    ("India Gate", INDIA_GATE), ("Gateway of India", GATEWAY), ("Golden Temple", GOLDEN), ("Varanasi ghat", GHATS),
    ("Marine Drive", MARINE),
    # misspellings / speech-to-text spellings
    ("Charminaar", CHARMINAR), ("char minar", CHARMINAR), ("Hawa Mehal", HAWA), ("Amber Fort", AMER), ("Taj Mehal", TAJ),
    ("Indiagate", INDIA_GATE), ("Gate way of India", GATEWAY), ("Golden Tempel", GOLDEN), ("Marin Drive", MARINE),
    ("Kutub Minar", QUTUB),
]


def _is(hit, target):
    lat, lng, km = target
    return gms.haversine_meters(float(hit["latitude"]), float(hit["longitude"]), lat, lng) <= km * 1000


def main() -> int:
    if not gms.GOOGLE_MAPS_SERVER_KEY:
        print("No Google key in backend/.env")
        return 1
    rows, total_calls, good = [], 0, 0
    for q, target in CASES:
        if "--fresh" in sys.argv:
            gms.cache.d.clear()
        found = places.search_places_detailed(q)
        total_calls += found.google_calls
        if found.unavailable:
            rows.append((q, "-", "-", "-", "QUOTA/PAUSED", found.google_calls))
            continue
        if not found.results:
            rows.append((q, "(nothing)", "-", "-", "no", found.google_calls))
            continue
        top = found.results[0]
        c, s = city_state(top)
        if found.ambiguous:
            names = [x.get("name") for x in found.choices]
            ok = any(_is(x, target) for x in found.choices)
            verdict = "asks; intended among choices" if ok else "asks; intended NOT among choices"
            shown = "asks: " + " / ".join(names)
        else:
            ok = _is(top, target)
            verdict = "yes" if ok else "no"
            shown = top.get("name")
        good += ok
        rows.append((q, shown, c or s or "-", top.get("kind"), verdict, found.google_calls))

    print("| # | Query | Top result (or choices) | City | Kind | Intended? | Google calls |")
    print("|---|---|---|---|---|---|---|")
    for i, (q, shown, c, kind, verdict, calls) in enumerate(rows, 1):
        print(f"| {i} | {q} | {shown} | {c} | {kind} | {verdict} | {calls} |")
    print(f"\nIntended (top, or among the choices when it asks): {good}/{len(CASES)}")
    print(f"Google calls: {total_calls} for {len(CASES)} searches, average {total_calls / len(CASES):.2f} per search")

    if "--voice" in sys.argv:
        from redis_client import redis_conn
        from voice import agent
        user, conv = f"usr_mapeval_{uuid.uuid4().hex[:6]}", f"conv_{uuid.uuid4().hex[:6]}"
        print("\nVoice (real OpenAI + real Google):")
        try:
            for phrase in ("4 minar kahan hai", "char minar dikhao"):
                r = agent.run_agent(phrase, "hi", user_id=user, conversation_id=conv, screen="/", trip=None, redis_conn=redis_conn)
                print(f"  '{phrase}' -> action={r.action} google_calls={r.google_calls} reply={r.reply_text!r}")
        finally:
            for key in redis_conn.scan_iter(f"voice:*{user}*"):
                redis_conn.delete(key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
