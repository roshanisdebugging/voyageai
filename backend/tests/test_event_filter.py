"""
Home / Explore highlights: past, undated and far-future events are never shown (the code decides, not the model).
A fixed "today" (26 Nov 2026), local Redis for the cache path, the AI and pictures simulated.
Run from backend/: python -m tests.test_event_filter
"""
import contextlib
import io
import json
import os
import sys
import uuid
from datetime import date
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

import trips_service as TS  # noqa: E402
from redis_client import redis_conn  # noqa: E402

TODAY = date(2026, 11, 26)
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" and not cond else ""), flush=True)


def ev(title, start=None, end=None, **extra):
    e = {"id": title.lower().replace(" ", "_"), "title": title, "date": "Upcoming Date / Season", **extra}
    if start is not None:
        e["start_date"] = start
    if end is not None:
        e["end_date"] = end
    return e


# ---------------- the rule

kept, c = TS.filter_upcoming_events([ev("Past", "2026-11-01", "2026-11-03")], TODAY)
check("past event dropped", kept == [] and c["dropped_past"] == 1, c)
kept, c = TS.filter_upcoming_events([ev("Ongoing", "2026-11-20", "2026-11-28")], TODAY)
check("ongoing event (started before, ends after today) kept", [k["title"] for k in kept] == ["Ongoing"], c)
kept, c = TS.filter_upcoming_events([ev("Ends today", "2026-11-25", "2026-11-26")], TODAY)
check("event ending today kept", len(kept) == 1, c)
kept, c = TS.filter_upcoming_events([ev("One day today", "2026-11-26")], TODAY)
check("one-day event today (no end_date) kept, end = start", len(kept) == 1 and kept[0]["end_date"] == "2026-11-26", kept)
kept, c = TS.filter_upcoming_events([ev("Soon", "2027-01-10", "2027-01-12")], TODAY)
check("upcoming within 180 days kept", len(kept) == 1, c)
kept, c = TS.filter_upcoming_events([ev("Day 180", "2027-05-25", "2027-05-25")], TODAY)
check("exactly 180 days ahead kept", len(kept) == 1 and (date(2027, 5, 25) - TODAY).days == TS.EVENT_MAX_DAYS_AHEAD, c)
kept, c = TS.filter_upcoming_events([ev("Day 181", "2027-05-26", "2027-05-26")], TODAY)
check("181 days ahead dropped as far", kept == [] and c["dropped_far"] == 1, c)
kept, c = TS.filter_upcoming_events([ev("Far", "2027-10-01", "2027-10-02")], TODAY)
check("beyond 180 days dropped", kept == [] and c["dropped_far"] == 1, c)

undated = [ev("No dates"), ev("Null", None, None, start_date=None), ev("Words", "14 Nov", "15 Nov"),
           ev("Slashes", "26/12/2026", "26/12/2026"), ev("Month only", "2026-12"), ev("Bad day", "2026-02-30", "2026-02-30"),
           ev("With time", "2026-12-01T18:00:00", "2026-12-01"), ev("Number", 20261201, 20261201),
           ev("End before start", "2026-12-10", "2026-12-01"), ev("Bad end", "2026-12-10", "soon"), "not an event", None]
kept, c = TS.filter_upcoming_events(undated, TODAY)
check("missing, null and wrong-format dates all dropped", kept == [] and c["dropped_undated"] == 10 and c["raw"] == 10, c)
kept, c = TS.filter_upcoming_events(None, TODAY)
check("no events list at all -> empty", kept == [] and c["raw"] == 0)

mixed = [ev("C late", "2027-02-01", "2027-02-02"), ev("A ongoing", "2026-11-25", "2026-12-05"),
         ev("Gone", "2024-11-14", "2024-11-14"), ev("B soon", "2026-12-24", "2026-12-25"), ev("Undated")]
kept, c = TS.filter_upcoming_events(mixed, TODAY)
check("kept events sorted by start date", [k["title"] for k in kept] == ["A ongoing", "B soon", "C late"], [k["title"] for k in kept])
check("counts add up", c == {"raw": 5, "kept": 3, "dropped_past": 1, "dropped_undated": 1, "dropped_far": 0}, c)
check("display date is the checked start_date", [k["date"] for k in kept] == ["2026-11-25", "2026-12-24", "2027-02-01"])
check("camelCase startDate/endDate also read", len(TS.filter_upcoming_events([{"title": "x", "startDate": "2026-12-01", "endDate": "2026-12-02"}], TODAY)[0]) == 1)

# ---------------- the reported cache: Dev Deepavali 2024 and Sarnath Music Festival 2024

CITY = f"Testvaranasi{uuid.uuid4().hex[:6]}"
key = f"cache:spotlight:{CITY.lower()}"
stale = {"destination": CITY, "region": "Uttar Pradesh", "overview": "Test overview.",
         "activities": [{"id": "act_1", "title": "Dashashwamedh Ghat", "category": "Sights", "coordinates": [25.3068, 83.0104]}],
         "events": [{"id": "evt_1", "title": "Dev Deepavali", "date": "14 Nov 2024", "start_date": "2024-11-14", "end_date": "2024-11-14"},
                    {"id": "evt_2", "title": "Sarnath International Music Festival", "date": "February 2024"}]}
redis_conn.setex(key, 600, json.dumps(stale))
log = io.StringIO()
try:
    with mock.patch.object(TS, "_today_ist", lambda: TODAY), mock.patch.object(TS, "attach_highlight_images", lambda d, city: d), \
            mock.patch("ai_provider.complete_json", side_effect=AssertionError("cache hit expected")), contextlib.redirect_stdout(log):
        out = TS.generate_live_destination_highlights(CITY)
finally:
    redis_conn.delete(key)
check("cached Dev Deepavali 2024 + Sarnath 2024 -> no events", out["events"] == [], out["events"])
check("cached places untouched", [a["title"] for a in out["activities"]] == ["Dashashwamedh Ghat"])
line = next((ln for ln in log.getvalue().splitlines() if ln.startswith("[EVENTS]")), "")
check("log line on the cache path (counts only)",
      line == f"[EVENTS] city={CITY.title()} raw=2 kept=0 dropped_past=1 dropped_undated=1 dropped_far=0", line)

# ---------------- generation: filtered before caching, no second AI call, prompt carries today's date

CITY2 = f"Testcity{uuid.uuid4().hex[:6]}"
key2 = f"cache:spotlight:{CITY2.lower()}"
prompts = []


def model(prompt, **kw):
    prompts.append(prompt)
    return json.dumps({"destination": CITY2, "overview": "x", "activities": [{"id": "a", "title": "Place"}],
                       "events": [ev("Old fair", "2025-01-10", "2025-01-12"), ev("Winter fest", "2026-12-20", "2026-12-22"),
                                  ev("Guess", None)]})


log = io.StringIO()
try:
    with mock.patch.object(TS, "_today_ist", lambda: TODAY), mock.patch.object(TS, "attach_highlight_images", lambda d, city: d), \
            mock.patch("ai_provider.complete_json", model), contextlib.redirect_stdout(log):
        out = TS.generate_live_destination_highlights(CITY2)
    cached = json.loads(redis_conn.get(key2) or "{}")
finally:
    redis_conn.delete(key2)
check("generation: only the real upcoming event kept", [e["title"] for e in out["events"]] == ["Winter fest"], out["events"])
check("generation: one AI call only (no retry to fill the gap)", len(prompts) == 1)
check("generation: the cache holds the filtered events", [e["title"] for e in cached.get("events", [])] == ["Winter fest"])
check("prompt gives today's date and asks for ISO dates", "today is 2026-11-26" in prompts[0] and '"start_date": "YYYY-MM-DD"' in prompts[0]
      and "leave the event out" in prompts[0])
check("generation log line", f"[EVENTS] city={CITY2.title()} raw=3 kept=1 dropped_past=1 dropped_undated=1 dropped_far=0" in log.getvalue())

prompts.clear()


def model_none(prompt, **kw):
    prompts.append(prompt)
    return json.dumps({"destination": CITY2, "overview": "x", "activities": [{"id": "a", "title": "Place"}],
                       "events": [ev("Old fair", "2025-01-10", "2025-01-12")]})


try:
    with mock.patch.object(TS, "_today_ist", lambda: TODAY), mock.patch.object(TS, "attach_highlight_images", lambda d, city: d), \
            mock.patch("ai_provider.complete_json", model_none), contextlib.redirect_stdout(io.StringIO()):
        out = TS.generate_live_destination_highlights(CITY2)
finally:
    redis_conn.delete(key2)
check("all events gone -> empty list, places kept, no second call", out["events"] == [] and len(out["activities"]) == 1 and len(prompts) == 1)

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
