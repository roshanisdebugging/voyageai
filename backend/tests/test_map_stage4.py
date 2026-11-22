"""
Map stage 4 (clean-up and safety). No network calls.
Item 1: key names (new name first, old names as fallback with a name-only warning).
Run from backend/: python -m tests.test_map_stage4
"""
import contextlib
import io
import os
import sys
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

from services import maps_keys  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


def resolve(env):
    maps_keys._warned.clear()
    clean = {k: v for k, v in os.environ.items() if k not in ("GOOGLE_MAPS_SERVER_KEY", "GOOGLE_MAPS_API_KEY", "GOOGLE_MAP_DEMO_KEY")}
    buf = io.StringIO()
    with mock.patch.dict(os.environ, {**clean, **env}, clear=True), contextlib.redirect_stdout(buf):
        return maps_keys.resolve_server_key(), buf.getvalue()


# ---------------- 1. key names
key, log = resolve({"GOOGLE_MAPS_SERVER_KEY": "new-value-123", "GOOGLE_MAPS_API_KEY": "old-value-456"})
check("new name GOOGLE_MAPS_SERVER_KEY wins, no warning", key == "new-value-123" and log == "", log)
for old in ("GOOGLE_MAPS_API_KEY", "GOOGLE_MAP_DEMO_KEY"):
    key, log = resolve({old: "old-value-789"})
    check(f"old name {old} still read for one release", key == "old-value-789")
    check(f"{old}: one-line warning with the name only, never the value",
          old in log and "GOOGLE_MAPS_SERVER_KEY" in log and "old-value-789" not in log and log.count("\n") == 1, log.strip())
key, log = resolve({})
check("no key at all -> '' (callers then say 'not available')", key == "" and log == "")

# ---------------- 2. Routes caching off by default (Google terms 19.3: only lat/lng may be cached)
from services import routes_service  # noqa: E402
_saved = os.environ.pop("ROUTES_CACHE_TTL_S", None)
check("ROUTES_CACHE_TTL_S unset -> 0 (route results not cached)", routes_service.cache_ttl_s() == 0)
with mock.patch.dict(os.environ, {"ROUTES_CACHE_TTL_S": "oops"}):
    check("bad ROUTES_CACHE_TTL_S -> 0, not a cache", routes_service.cache_ttl_s() == 0)
with mock.patch.dict(os.environ, {"ROUTES_CACHE_TTL_S": "1800"}):
    check("setting kept: 1800 when asked", routes_service.cache_ttl_s() == 1800)
if _saved is not None:
    os.environ["ROUTES_CACHE_TTL_S"] = _saved

# ---------------- 4. attribution travels with Google Maps notes (voice)
from voice import messages as vmsg  # noqa: E402
from voice.tools import lookups  # noqa: E402
HIT = [{"id": "ChIJhawa", "name": "Hawa Mahal", "latitude": 26.9239, "longitude": 75.8267, "types": ["monument"]}]
walk = lookups.get_travel_time("Hawa Mahal", "walk", "en", origin=(26.9124, 75.7873), search_fn=lambda q: HIT,
                               route_fn=lambda *a, **k: {"distance_m": 1900, "duration_s": 1600, "mode": "walk",
                                                         "warning": "This route has restricted usage or private roads.", "cached": False})
check("Google route warning note carries 'Google Maps' attribution", walk.note and walk.note_attribution == "Google Maps")
car = lookups.get_travel_time("Hawa Mahal", "car", "en", origin=(26.9124, 75.7873), search_fn=lambda q: HIT,
                              route_fn=lambda *a, **k: {"distance_m": 6800, "duration_s": 1300, "mode": "drive", "warning": None, "cached": False})
check("no note -> no attribution field", car.note is None and car.note_attribution is None)
r1 = vmsg.reply("t1", "x", None, "audio/wav", 0, note="This route has tolls.", note_attribution="Google Maps")
r2 = vmsg.reply("t2", "x", None, "audio/wav", 0, note=None, note_attribution="Google Maps")
r3 = vmsg.reply("t3", "x", None, "audio/wav", 0, note="Details badal sakti hain.")
check("reply sends note_attribution only with a note", r1.get("note_attribution") == "Google Maps"
      and "note_attribution" not in r2 and "note_attribution" not in r3)

print(f"\n{sum(results)}/{len(results)} passed", flush=True)
sys.exit(0 if all(results) else 1)
