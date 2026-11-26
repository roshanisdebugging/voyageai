"""
Card stops when Google returns several results (bug: every "ambiguous" search was marked unresolved, so
Dashashwamedh Ghat, Kashi Vishwanath Temple and Sarnath all showed "Location not found").
Google is simulated (the shared search's result shape); nothing real is called.
Run from backend/: python -m tests.test_pilgrimage_resolve
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'app.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)
import models_db, models_trip, models_itinerary, models_package, models_place  # noqa: E401,E402,F401
database.Base.metadata.create_all(bind=database.engine)

import pilgrimage  # noqa: E402
import plan_card_itinerary as PCI  # noqa: E402
import trip_lifecycle  # noqa: E402
from models_trip import TripModel  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" and not cond else ""), flush=True)


VARANASI = (25.3176, 82.9739)


def hit(pid, name, lat, lng, where="Varanasi, Uttar Pradesh"):
    return {"place_id": pid, "id": pid, "name": name, "displayName": f"{name}, {where}, India", "latitude": lat, "longitude": lng}


def google(table, ambiguous=True):
    """A search function: query -> the results listed for the first key it starts with (Google order kept)."""
    calls = []

    def search(query):
        calls.append(query)
        for key, rows in table.items():
            if query.lower().startswith(key.lower()):
                return SimpleNamespace(results=list(rows), ambiguous=ambiguous and len(rows) > 1, unavailable=False)
        return SimpleNamespace(results=[], ambiguous=False, unavailable=False)
    search.calls = calls
    return search


# ---------------- name matching

check("partial match: 'Kashi Vishwanath Temple' vs 'Shri Kashi Vishwanath Mandir'",
      PCI.name_score("Kashi Vishwanath Temple", "Shri Kashi Vishwanath Mandir") == 1.0)
check("spelling variant: 'Dashashwamedh Ghat' vs 'Dasaswamedh Ghat'", PCI.name_score("Dashashwamedh Ghat", "Dasaswamedh Ghat") == 1.0)
check("bracket alternatives: 'Sarnath (Dhamek Stupa and ...)' vs 'Dhamek Stupa'",
      PCI.name_score("Sarnath (Dhamek Stupa and Archaeological Museum)", "Dhamek Stupa") == 1.0)
check("unrelated names score low", PCI.name_score("Kashi Vishwanath Temple", "Hotel Ganges View") < PCI.NAME_MATCH_MIN)
check("radius constant is 25 km", PCI.RESOLVE_RADIUS_KM == 25.0)

# ---------------- (a) several results, the right one first

s = google({"Kashi Vishwanath Temple": [hit("ChIJkvt", "Shri Kashi Vishwanath Temple", 25.3109, 83.0107),
                                         hit("ChIJgate4", "Kashi Vishwanath Gate No 4", 25.3106, 83.0118),
                                         hit("ChIJnew", "New Vishwanath Temple BHU", 25.2830, 82.9900)]})
place, why = PCI.resolve("Kashi Vishwanath Temple", "Varanasi", s, VARANASI)
check("(a) several results, right one first -> resolved to it", why == "ok" and place["place_id"] == "ChIJkvt", (why, place))
check("(a) searched as '<stop name> <city>'", s.calls == ["Kashi Vishwanath Temple Varanasi"], s.calls)
check("(a) marked as resolved from several results", place and place["ambiguous"] is True)

# ---------------- (b) far-away top result, right place second

s = google({"Kashi Vishwanath Temple": [hit("ChIJuttarkashi", "Kashi Vishwanath Temple", 30.7268, 78.4354, "Uttarkashi, Uttarakhand"),
                                         hit("ChIJkvt", "Shri Kashi Vishwanath Temple", 25.3109, 83.0107)]})
place, why = PCI.resolve("Kashi Vishwanath Temple", "Varanasi", s, VARANASI)
check("(b) far-away top result skipped, the Varanasi one resolved", why == "ok" and place["place_id"] == "ChIJkvt", (why, place))

# ---------------- (c) no results

place, why = PCI.resolve("Kashi Vishwanath Temple", "Varanasi", google({}), VARANASI)
check("(c) no results -> unresolved, reason no_results", place is None and why == "no_results", why)

# ---------------- (d) only far results

s = google({"Kashi Vishwanath Temple": [hit("ChIJuttarkashi", "Kashi Vishwanath Temple", 30.7268, 78.4354, "Uttarkashi, Uttarakhand"),
                                         hit("ChIJgupt", "Kashi Vishwanath Temple", 30.5276, 79.0794, "Guptkashi, Uttarakhand")]})
place, why = PCI.resolve("Kashi Vishwanath Temple", "Varanasi", s, VARANASI)
check("(d) only far results -> unresolved, reason outside_radius", place is None and why == "outside_radius", why)

# no name match (near, but unrelated)
s = google({"Kashi Vishwanath Temple": [hit("ChIJhotel", "Hotel Ganges View", 25.3000, 83.0100)]})
place, why = PCI.resolve("Kashi Vishwanath Temple", "Varanasi", s, VARANASI)
check("near but unrelated -> unresolved, reason no_name_match", place is None and why == "no_name_match", why)
check("Google paused -> unresolved, reason unavailable",
      PCI.resolve("X Y", "Varanasi", lambda q: SimpleNamespace(results=[], ambiguous=False, unavailable=True), VARANASI) == (None, "unavailable"))

# ---------------- (e) the Varanasi card, as in the log (3, 5 and 4 results, all ambiguous)

LOGLIKE = google({
    "Dashashwamedh Ghat": [hit("ChIJdash", "Dashashwamedh Ghat", 25.3068, 83.0104),
                           hit("ChIJdashroad", "Dashashwamedh Road", 25.3075, 83.0060),
                           hit("ChIJdashpolice", "Dashashwamedh Police Station", 25.3080, 83.0070)],
    "Kashi Vishwanath Temple": [hit("ChIJkvt", "Shri Kashi Vishwanath Temple", 25.3109, 83.0107),
                                hit("ChIJgate4", "Kashi Vishwanath Gate No 4", 25.3106, 83.0118),
                                hit("ChIJnew", "New Vishwanath Temple BHU", 25.2830, 82.9900),
                                hit("ChIJuttarkashi", "Kashi Vishwanath Temple", 30.7268, 78.4354, "Uttarkashi, Uttarakhand"),
                                hit("ChIJcorridor", "Kashi Vishwanath Dham Corridor", 25.3110, 83.0115)],
    "Sarnath": [hit("ChIJdhamek", "Dhamek Stupa", 25.3811, 83.0243, "Sarnath, Varanasi, Uttar Pradesh"),
                hit("ChIJsarmus", "Archaeological Museum Sarnath", 25.3790, 83.0240, "Sarnath, Varanasi, Uttar Pradesh"),
                hit("ChIJsarloc", "Sarnath", 25.3762, 83.0227, "Varanasi, Uttar Pradesh"),
                hit("ChIJsardelhi", "Sarnath Hotel", 28.6328, 77.2197, "New Delhi, Delhi")],
})
V = pilgrimage.get_card("varanasi-kashi-yatra")
expected = {"Dashashwamedh Ghat": "ChIJdash", "Kashi Vishwanath Temple": "ChIJkvt", V.days[2].stops[0].name: "ChIJdhamek"}
for d in V.days:
    for stop in d.stops:
        place, why = PCI.resolve(stop.name, stop.city, LOGLIKE, VARANASI)
        check(f"(e) '{stop.name[:30]}' resolves (several results)", why == "ok" and place["place_id"] == expected[stop.name], (why, place))

start = (date.today() + timedelta(days=12)).isoformat()
trip = TripModel(id=f"trip_r{uuid.uuid4().hex[:8]}", user_id="usr_res", title="Varanasi Tour Package", status="PLANNING",
                 itinerary_status="GENERATING", start_date=start, end_date=(date.fromisoformat(start) + timedelta(days=2)).isoformat(),
                 total_days=3, destination_json=json.dumps({"name": "Varanasi", "city": "Varanasi", "latitude": VARANASI[0], "longitude": VARANASI[1]}),
                 travelers_json="[]", created_at="t", updated_at="t",
                 preferences_snapshot_json=json.dumps({"planCard": trip_lifecycle._plan_card_meta(V.id, {"name": "Varanasi", "city": "Varanasi"})}))
log = io.StringIO()
with database.SessionLocal() as db, contextlib.redirect_stdout(log):
    db.add(trip)
    db.commit()
    PCI.generate(trip, db, V, search_fn=LOGLIKE, complete_fn=lambda p: (_ for _ in ()).throw(AssertionError("no AI")))
    meta = db.query(TripModel).filter(TripModel.id == trip.id).first().preferences_snapshot["planCard"]
line = next((ln for ln in log.getvalue().splitlines() if ln.startswith("[PILGRIMAGE] built")), "")
check("(e) whole card built: 3 resolved, 3 from several results, 0 unresolved", "resolved=3 resolved_from_ambiguous=3 unresolved=0 reasons=none" in line, line)
check("(e) no stop flagged on the trip", not any(v["unresolved"] for v in meta["stops"].values()))

# unresolved reasons reach the log and the trip
trip2 = TripModel(id=f"trip_r{uuid.uuid4().hex[:8]}", user_id="usr_res", title="Varanasi Tour Package", status="PLANNING",
                  itinerary_status="GENERATING", start_date=start, end_date=(date.fromisoformat(start) + timedelta(days=2)).isoformat(),
                  total_days=3, destination_json=json.dumps({"name": "Varanasi", "city": "Varanasi", "latitude": VARANASI[0], "longitude": VARANASI[1]}),
                  travelers_json="[]", created_at="t", updated_at="t",
                  preferences_snapshot_json=json.dumps({"planCard": trip_lifecycle._plan_card_meta(V.id, {"name": "Varanasi", "city": "Varanasi"})}))
PARTIAL = google({"Kashi Vishwanath Temple": [hit("ChIJuttarkashi", "Kashi Vishwanath Temple", 30.7268, 78.4354, "Uttarkashi")],
                  "Sarnath": [hit("ChIJhotel", "Hotel Buddha", 25.3800, 83.0200)]})
log = io.StringIO()
with database.SessionLocal() as db, contextlib.redirect_stdout(log):
    db.add(trip2)
    db.commit()
    PCI.generate(trip2, db, V, search_fn=PARTIAL, complete_fn=lambda p: (_ for _ in ()).throw(AssertionError("no AI")))
    meta = db.query(TripModel).filter(TripModel.id == trip2.id).first().preferences_snapshot["planCard"]
line = next((ln for ln in log.getvalue().splitlines() if ln.startswith("[PILGRIMAGE] built")), "")
check("reasons logged: no_results, outside_radius, no_name_match",
      "resolved=0" in line and "unresolved=3" in line and "reasons=no_name_match:1,no_results:1,outside_radius:1" in line, line)
check("each unresolved stop keeps its reason on the trip",
      sorted(v["reason"] for v in meta["stops"].values()) == ["no_name_match", "no_results", "outside_radius"])

database.engine.dispose()
shutil.rmtree(SCRATCH, ignore_errors=True)
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
