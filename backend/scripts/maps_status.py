"""
Which Google Maps server key is in use and which of its APIs are paused. No Google call; never prints a key
(only the variable name and an 8-character one-way fingerprint).

    python -m scripts.maps_status            # the same line the server prints at startup
    python -m scripts.maps_status --clear    # also delete the pause flags of the CURRENT key (other keys' flags stay)

Reads backend/.env like the server does. The server reads it only at startup: if the fingerprint here differs from
the server's startup line, restart the server. --clear takes effect on a running server at once.
"""
import argparse
import os
import sys
from typing import List, Optional

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BACKEND_DIR, ".env"), override=True)   # before the Redis client and the key are read

from services import google_maps_service as gms  # noqa: E402


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="maps_status", description="Google Maps key and pause flags")
    parser.add_argument("--clear", action="store_true", help="delete the pause flags of the current key only")
    args = parser.parse_args(argv)

    print(gms.status_line(), flush=True)
    if not args.clear:
        return 0
    if not gms.KEY_FINGERPRINT:
        print("[MAPS] nothing to clear: no server key set", flush=True)
        return 0
    try:
        cleared = gms.clear_pauses()
    except Exception as e:
        print(f"[MAPS] could not clear: Redis not reachable ({type(e).__name__})", flush=True)
        return 1
    print(f"[MAPS] cleared for fp={gms.KEY_FINGERPRINT}: {', '.join(cleared) or 'nothing was paused'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
