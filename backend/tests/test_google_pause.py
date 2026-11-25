"""
Google pause flags belong to the key in use (services/google_maps_service.pause_key). No network, no real Redis.
Key A's pause never affects key B; same key: pauses and expires as before; one skip line per API per minute; no line
holds the key or more than its 8-character fingerprint; startup line; scripts/maps_status.py --clear.
Run from backend/: python -m tests.test_google_pause
"""
import asyncio
import contextlib
import fnmatch
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest import mock

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
KEY_A = "AIza-test-key-A-not-real-0123456789"
KEY_B = "AIza-test-key-B-not-real-9876543210"
os.environ["GOOGLE_MAPS_SERVER_KEY"] = KEY_A
for old in ("GOOGLE_MAPS_API_KEY", "GOOGLE_MAP_DEMO_KEY"):
    os.environ.pop(old, None)
os.environ.setdefault("DATABASE_URL", "postgresql://x:y@127.0.0.1:1/none")

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

import redis  # noqa: E402

import image_service as IS  # noqa: E402
from scripts import maps_status  # noqa: E402
from services import google_maps_service as gms  # noqa: E402
from services import routes_service as rs  # noqa: E402

results = []
LOG = io.StringIO()        # everything the code under test printed


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if (detail != "" and not cond) else ""), flush=True)


class FakeRedis:
    """Strings with expiry on a clock the test moves."""

    def __init__(self):
        self.d, self.now, self.down = {}, 1000.0, False

    def _live(self, k):
        if self.down:
            raise redis.ConnectionError("down")
        if k in self.d and self.d[k][1] is not None and self.d[k][1] <= self.now:
            del self.d[k]
        return k in self.d

    def get(self, k):
        return self.d[k][0] if self._live(k) else None

    def set(self, k, v, ex=None):
        self._live(k)
        self.d[k] = (v, None if ex is None else self.now + ex)

    def ttl(self, k):
        if not self._live(k):
            return -2
        return -1 if self.d[k][1] is None else int(self.d[k][1] - self.now)

    def delete(self, k):
        return 1 if self._live(k) and self.d.pop(k) else 0

    def scan_iter(self, match):
        return [k for k in list(self.d) if self._live(k) and fnmatch.fnmatchcase(k, match)]

    def incr(self, k):
        return 1

    def expire(self, k, ttl):
        pass


R = FakeRedis()
gms.redis_conn = R
IS.redis_conn = R


class Clock:
    now = 5000.0


class FakeTime:
    """time for google_maps_service only: the skip log's clock and the in-memory expiry."""
    monotonic = staticmethod(lambda: Clock.now)
    time = staticmethod(lambda: Clock.now)


gms.time = FakeTime


def use_key(key):
    """What importing the service with this key in the environment gives (also used by image_service at run time)."""
    os.environ["GOOGLE_MAPS_SERVER_KEY"] = key
    gms.GOOGLE_MAPS_SERVER_KEY = key
    gms.KEY_FINGERPRINT = gms.key_fingerprint(key)


def fresh(key=KEY_A):
    R.d.clear()
    R.down = False
    gms._in_memory_cache.clear()
    gms._skip_logged_at.clear()
    use_key(key)


def run(fn, *a):
    """(result or exception, printed text)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            out = fn(*a)
            if asyncio.iscoroutine(out):
                out = asyncio.run(out)
        except Exception as e:      # noqa: BLE001 - the test looks at it
            out = e
    LOG.write(buf.getvalue())
    return out, buf.getvalue()


def resp(status, body):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = body
    r.headers = {}
    return r


DAILY = resp(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded, limit 'GetPlaceRequest per day'"}})
MINUTE = resp(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "limit 'requests per minute'",
                              "details": [{"metadata": {"quota_limit": "AutocompletePerMinutePerProject"}}]}})
FP_A, FP_B = (hashlib.sha256(k.encode()).hexdigest()[:8] for k in (KEY_A, KEY_B))

# ---------------------------------------------------------------- 1. fingerprint and name
check("fingerprint built at import: first 8 hex of SHA-256", gms.KEY_FINGERPRINT == FP_A and re.fullmatch(r"[0-9a-f]{8}", FP_A))
check("no key -> empty fingerprint", gms.key_fingerprint("") == "")
check("source is the variable name", gms.KEY_SOURCE == "GOOGLE_MAPS_SERVER_KEY")
check("flag name", gms.pause_key("textsearch") == f"gmaps:paused:{FP_A}:textsearch")
hits = [str(p.relative_to(BACKEND_DIR)) for p in BACKEND_DIR.rglob("*.py")
        if "venv" not in p.parts and "tests" not in p.parts
        and re.search(r"""f?["']gmaps:paused""", p.read_text(encoding="utf-8", errors="ignore"))]
check("one place builds the name", [h.replace("\\", "/") for h in hits] == ["services/google_maps_service.py"], hits)

# ---------------------------------------------------------------- 2. key A vs key B
for api in ("textsearch", "nearby", "autocomplete", "details", "geocode", "routes", "photo"):
    fresh()
    run(gms.mark_paused, api, DAILY)
    a = run(gms.is_paused, api)[0]
    use_key(KEY_B)
    b = run(gms.is_paused, api)[0]
    use_key(KEY_A)
    check(f"{api}: paused with key A, not with key B, still paused back on A", a is True and b is False
          and run(gms.is_paused, api)[0] is True)

fresh()
run(IS._mark_paused, "textsearch", DAILY)
check("images: a pause from image_service is seen by place search (same key)", run(gms.is_paused, "textsearch")[0] is True
      and IS._is_paused("textsearch") is True)
use_key(KEY_B)
check("images: not paused with key B", run(IS._is_paused, "textsearch")[0] is False)

fresh()
for api in ("textsearch", "photo", "routes"):
    R.set(f"gmaps:paused:{api}", "true", ex=9999)
check("old unscoped flags are ignored", not any(run(gms.is_paused, a)[0] for a in ("textsearch", "photo", "routes"))
      and not run(IS._is_paused, "photo")[0] and gms.active_pauses() == [])


class FakeHttp:
    calls = 0

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        FakeHttp.calls += 1
        return resp(200, {"routes": [{"distanceMeters": 1200, "duration": "300s", "polyline": {"encodedPolyline": "x"}}]})


with mock.patch.object(rs.httpx, "AsyncClient", FakeHttp):
    fresh()
    run(gms.mark_paused, "routes", DAILY)
    out, _ = run(rs.compute_route, 26.9, 75.8, 26.98, 75.85, "drive")
    check("routes with paused key A: refused, no Google call", isinstance(out, rs.RouteUnavailable) and FakeHttp.calls == 0, out)
    use_key(KEY_B)
    out, _ = run(rs.compute_route, 26.9, 75.8, 26.98, 75.85, "drive")
    check("routes with key B: Google is called", FakeHttp.calls == 1 and isinstance(out, dict) and out["distance_m"] == 1200, out)

# A real process restart with another key: the import alone gives the other fingerprint.
code = ("import dotenv; dotenv.load_dotenv=lambda *a,**k: None\n"
        "from services import google_maps_service as g; print(g.KEY_FINGERPRINT + '|' + g.pause_key('routes'))")
env = {**os.environ, "GOOGLE_MAPS_SERVER_KEY": KEY_B}
out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND_DIR, env=env, capture_output=True, text=True).stdout.strip()
check("new process with key B: its own fingerprint and flag names", out == f"{FP_B}|gmaps:paused:{FP_B}:routes", out)

# ---------------------------------------------------------------- 3. same key: duration and expiry as before
fresh()
run(gms.mark_paused, "autocomplete", MINUTE)
check("per-minute limit: 60 s", R.ttl(gms.pause_key("autocomplete")) == 60)
R.now += 59
check("still paused at 59 s", run(gms.is_paused, "autocomplete")[0] is True)
R.now += 2
check("expired after 60 s", run(gms.is_paused, "autocomplete")[0] is False)
fresh()
_, text = run(gms.mark_paused, "details", DAILY)
ttl = R.ttl(gms.pause_key("details"))
check("daily limit: until Google's reset", abs(ttl - gms._seconds_to_google_reset()) <= 2 and 60 < ttl <= 86460, ttl)
check("the pause line is unchanged", re.fullmatch(r"\[GOOGLE QUOTA\] details paused for \d+ s\n", text), text)
R.now += ttl - 1
check("paused until just before the reset", run(gms.is_paused, "details")[0] is True)
R.now += 2
check("not paused after the reset", run(gms.is_paused, "details")[0] is False)
check("stored value is only 'true'", run(gms.mark_paused, "details", DAILY) and R.get(gms.pause_key("details")) == json.dumps(True))

fresh()
run(gms.mark_paused, "nearby", MINUTE)
R.down = True
check("Redis down: this process still remembers its own pause", run(gms.is_paused, "nearby")[0] is True)
use_key(KEY_B)
check("Redis down: key B not paused", run(gms.is_paused, "nearby")[0] is False)
check("Redis down: image_service doesn't crash", run(IS._is_paused, "textsearch")[0] is False)

# ---------------------------------------------------------------- 4. skip log
fresh()
run(gms.mark_paused, "textsearch", DAILY)
R.set(gms.pause_key("textsearch"), "true", ex=680)
texts = [run(gms.is_paused, "textsearch")[1] for _ in range(20)]
want = f"[GOOGLE QUOTA] textsearch request skipped: paused, 680s left (fp={FP_A})\n"
check("20 skips in a minute: one line, with the api and the time left", "".join(texts) == want, texts)
Clock.now += 59
check("59 s later: still silent", run(gms.is_paused, "textsearch")[1] == "" and run(IS._is_paused, "textsearch")[1] == "")
Clock.now += 1
check("a minute later: one more line", run(gms.is_paused, "textsearch")[1].count("skipped") == 1
      and run(gms.is_paused, "textsearch")[1] == "")
run(gms.mark_paused, "routes", MINUTE)
check("another api has its own line", run(gms.is_paused, "routes")[1].startswith("[GOOGLE QUOTA] routes request skipped: paused, 60s left"))
check("not paused: no line", run(gms.is_paused, "details")[1] == "")
fresh()
R.set(gms.pause_key("photo"), "true", ex=300)
texts = [run(IS._is_paused, "photo")[1] for _ in range(5)]
check("images log their skips the same way", "".join(texts).count("photo request skipped: paused, 300s left") == 1
      and "".join(texts).count("\n") == 1, texts)

# ---------------------------------------------------------------- 5. startup line
fresh()
check("startup line, nothing paused", gms.status_line() == f"[MAPS] server key from GOOGLE_MAPS_SERVER_KEY fp={FP_A} paused=[]")
R.set(gms.pause_key("textsearch"), "true", ex=680)
R.set(gms.pause_key("details"), "true", ex=42)
R.set(f"gmaps:paused:{FP_B}:routes", "true", ex=500)
R.set("gmaps:paused:nearby", "true", ex=500)
check("startup line: this key's pauses with the time left", gms.status_line()
      == f"[MAPS] server key from GOOGLE_MAPS_SERVER_KEY fp={FP_A} paused=[details:42s, textsearch:680s]", gms.status_line())
LOG.write(gms.status_line())
R.down = True
check("Redis down: startup line says so, no crash", gms.status_line().endswith("paused=[unknown, Redis not reachable]"))
fresh("")
check("no key: startup line says so", gms.status_line() == "[MAPS] no server key set: Google Maps calls are off")
src = (BACKEND_DIR / "main.py").read_text(encoding="utf-8")
check("the server prints it once, at startup", src.count("status_line)") == 1
      and src.index("async def lifespan") < src.index("status_line)") < src.index("app = FastAPI("))

# ---------------------------------------------------------------- 6. scripts/maps_status.py
fresh()
R.set(gms.pause_key("textsearch"), "true", ex=680)
R.set(gms.pause_key("routes"), "true", ex=50)
R.set(f"gmaps:paused:{FP_B}:routes", "true", ex=500)
R.set("gmaps:paused:nearby", "true", ex=500)
R.set("img:calls:x", "3")
before = dict(R.d)
code_, text = run(maps_status.main, [])
check("status: same line, nothing deleted", code_ == 0 and text == gms.status_line() + "\n" and R.d == before, text)
run(gms.mark_paused, "details", DAILY)      # this one is also in the process's own memory
code_, text = run(maps_status.main, ["--clear"])
check("--clear: only the current key's flags are deleted", code_ == 0
      and sorted(R.d) == sorted(["gmaps:paused:nearby", f"gmaps:paused:{FP_B}:routes", "img:calls:x"]), sorted(R.d))
check("--clear: says what it deleted", text.endswith(f"[MAPS] cleared for fp={FP_A}: details, routes, textsearch\n"), text)
check("--clear: nothing paused -> says so", run(maps_status.main, ["--clear"])[1].endswith("nothing was paused\n"))
run(gms.mark_paused, "details", DAILY)
R.delete(gms.pause_key("details"))          # what --clear does from another process
check("a running server sees the clear at once (no stale in-memory copy)", run(gms.is_paused, "details")[0] is False)
R.down = True
code_, text = run(maps_status.main, ["--clear"])
check("--clear with Redis down: exit 1, plain message", code_ == 1 and "could not clear" in text, text)
fresh("")
R.set("gmaps:paused::routes", "true")
code_, text = run(maps_status.main, ["--clear"])
check("--clear without a key: deletes nothing", code_ == 0 and "nothing to clear" in text and len(R.d) == 1, text)

# ---------------------------------------------------------------- 7. nothing leaks
everything = LOG.getvalue()
check("no line holds a key, or a part of one", all(k[i:i + 8] not in everything for k in (KEY_A, KEY_B) for i in range(len(k) - 7)))
full = [hashlib.sha256(k.encode()).hexdigest() for k in (KEY_A, KEY_B)]
check("no more than 8 characters of the hash", FP_A in everything and all(h[:9] not in everything for h in full)
      and all(len(x) == 8 for x in re.findall(r"fp=([0-9a-f]+)", everything)))
fresh()
for api in ("textsearch", "routes"):
    run(gms.mark_paused, api, DAILY)
stored = "".join(list(R.d) + [v[0] for v in R.d.values()])
check("Redis holds only the 8-character fingerprint", KEY_A not in stored and full[0][:9] not in stored and FP_A in stored)

print(f"\n{sum(results)}/{len(results)} passed", flush=True)
sys.exit(0 if all(results) else 1)
