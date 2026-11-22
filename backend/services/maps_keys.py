"""
The Google Maps SERVER key (Places, Geocoding, Routes): GOOGLE_MAPS_SERVER_KEY.
The old names GOOGLE_MAPS_API_KEY and GOOGLE_MAP_DEMO_KEY are still read for one release; using one logs a
one-line warning with the variable NAME only (never the value).
No network calls, no heavy imports: scripts can use it too.
"""
import os

SERVER_KEY_NAME = "GOOGLE_MAPS_SERVER_KEY"
OLD_SERVER_KEY_NAMES = ("GOOGLE_MAPS_API_KEY", "GOOGLE_MAP_DEMO_KEY")
_warned = set()


def server_key_source() -> str:
    """Which variable the key comes from ('' when none is set)."""
    if os.getenv(SERVER_KEY_NAME, "").strip():
        return SERVER_KEY_NAME
    return next((n for n in OLD_SERVER_KEY_NAMES if os.getenv(n, "").strip()), "")


def resolve_server_key() -> str:
    name = server_key_source()
    if name and name != SERVER_KEY_NAME and name not in _warned:
        _warned.add(name)
        print(f"[MAPS] Using the old key name {name}; rename it to {SERVER_KEY_NAME} "
              f"(old names are read for one more release).", flush=True)
    return os.getenv(name, "").strip() if name else ""
