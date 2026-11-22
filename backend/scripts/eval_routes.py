"""
Map stage 3 real-key check: 10 routes across 3 Indian cities through routes_service.compute_route (no cache, so every
route is one real Google call). Prints origin, destination, mode, distance, time and ms. Never prints the key.

    python -m scripts.eval_routes
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
os.environ["ROUTES_CACHE_TTL_S"] = "0"   # measure real calls

from services import google_maps_service as gms  # noqa: E402
from services import routes_service as rs  # noqa: E402
from voice.tools.lookups import spoken_distance  # noqa: E402

P = {
    "Hawa Mahal": (26.9239, 75.8267), "Amer Fort": (26.9855, 75.8513), "Jaipur Junction": (26.9196, 75.7878),
    "Albert Hall": (26.9116, 75.8195), "Jaipur Airport": (26.8242, 75.8122),
    "India Gate": (28.6129, 77.2295), "Qutub Minar": (28.5245, 77.1855), "Red Fort": (28.6562, 77.2410),
    "Connaught Place": (28.6315, 77.2167),
    "Gateway of India": (18.9220, 72.8347), "Marine Drive": (18.9440, 72.8230), "CSMT": (18.9398, 72.8355),
    "Mumbai Airport T2": (19.0974, 72.8742),
}
CASES = [
    ("Jaipur", "Hawa Mahal", "Amer Fort", "drive"),
    ("Jaipur", "Jaipur Junction", "Hawa Mahal", "two_wheeler"),
    ("Jaipur", "Hawa Mahal", "Albert Hall", "walk"),
    ("Jaipur", "Hawa Mahal", "Jaipur Airport", "drive"),
    ("Delhi", "India Gate", "Qutub Minar", "drive"),
    ("Delhi", "Connaught Place", "Red Fort", "two_wheeler"),
    ("Delhi", "India Gate", "Connaught Place", "walk"),
    ("Mumbai", "Gateway of India", "Marine Drive", "drive"),
    ("Mumbai", "CSMT", "Gateway of India", "walk"),
    ("Mumbai", "Marine Drive", "Mumbai Airport T2", "two_wheeler"),
]


def fmt_dur(s):
    m = round(s / 60)
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60} min"


async def main() -> int:
    if not gms.GOOGLE_MAPS_SERVER_KEY:
        print("No Google key in backend/.env")
        return 1
    print("| # | City | From | To | Mode | Distance | Time | ms | Warning |")
    print("|---|---|---|---|---|---|---|---|---|")
    total_ms = calls = 0
    for i, (city, a, b, mode) in enumerate(CASES, 1):
        counter = gms.GoogleCallCounter()
        t = time.perf_counter()
        try:
            r = await rs.compute_route(*P[a], *P[b], mode, counter=counter)
            ms = int((time.perf_counter() - t) * 1000)
            row = f"{spoken_distance(r['distance_m'])} | {fmt_dur(r['duration_s'])} | {ms} | {r.get('warning') or '-'}"
        except rs.RouteUnavailable:
            ms = int((time.perf_counter() - t) * 1000)
            row = f"- | QUOTA/PAUSED | {ms} | -"
        except rs.RouteNotFound:
            ms = int((time.perf_counter() - t) * 1000)
            row = f"- | no route | {ms} | -"
        total_ms += ms
        calls += counter.count
        print(f"| {i} | {city} | {a} | {b} | {mode} | {row} |")
    print(f"\nGoogle calls: {calls}; average {total_ms // len(CASES)} ms per route")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
