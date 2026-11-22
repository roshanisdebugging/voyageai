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

print(f"\n{sum(results)}/{len(results)} passed", flush=True)
sys.exit(0 if all(results) else 1)
