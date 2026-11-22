"""
Google Maps key safety check (map stage 4). No network calls; never prints a key or any part of one.

    python -m scripts.check_keys            # errors fail (exit 1); warnings are listed
    python -m scripts.check_keys --strict   # warnings fail too (use before real users)

Checks:
- names: backend/.env has GOOGLE_MAPS_SERVER_KEY, frontend/.env has VITE_GOOGLE_MAPS_BROWSER_KEY;
  the old names (GOOGLE_MAPS_API_KEY, GOOGLE_MAP_DEMO_KEY, VITE_GOOGLE_MAP_DEMO_KEY) are flagged;
- the browser key and the server key are different variables: no server key in a VITE_ variable
  (that would ship it to every browser), no Google key at all in frontend/.env outside VITE_GOOGLE_MAPS_BROWSER_KEY;
- the two keys should be different keys (same value is fine for the demo key, a warning; an error with --strict);
- no key string (AIza + 35 characters) in any file tracked by git.
"""
import os
import re
import subprocess
import sys
from typing import Dict, List, Tuple

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{35}")
SERVER = "GOOGLE_MAPS_SERVER_KEY"
BROWSER = "VITE_GOOGLE_MAPS_BROWSER_KEY"
OLD_SERVER = ("GOOGLE_MAPS_API_KEY", "GOOGLE_MAP_DEMO_KEY")
OLD_BROWSER = ("VITE_GOOGLE_MAP_DEMO_KEY",)


def parse_env(path: str) -> Dict[str, str]:
    """KEY=value lines of a .env file ('' when the file is missing). Values stay in memory only."""
    out: Dict[str, str] = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
    return out


def check_envs(backend: Dict[str, str], frontend: Dict[str, str]) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    server = backend.get(SERVER) or next((backend[n] for n in OLD_SERVER if backend.get(n)), "")
    browser = frontend.get(BROWSER) or next((frontend[n] for n in OLD_BROWSER if frontend.get(n)), "")

    if not backend.get(SERVER):
        old = [n for n in OLD_SERVER if backend.get(n)]
        (warnings.append(f"backend/.env uses the old name {old[0]}; rename it to {SERVER}") if old
         else warnings.append(f"backend/.env has no {SERVER} (server-side Places, Geocoding and Routes are off)"))
    if not frontend.get(BROWSER):
        old = [n for n in OLD_BROWSER if frontend.get(n)]
        (warnings.append(f"frontend/.env uses the old name {old[0]}; rename it to {BROWSER}") if old
         else warnings.append(f"frontend/.env has no {BROWSER} (the map shows \"Map isn't available right now\")"))

    for name, value in frontend.items():
        if name.startswith("VITE_") and "SERVER" in name.upper() and value:
            errors.append(f"frontend/.env {name}: a server key in a VITE_ variable is shipped to every browser")
        if name.startswith("VITE_") and name not in (BROWSER,) + OLD_BROWSER and KEY_RE.search(value):
            errors.append(f"frontend/.env {name}: holds a Google key but is not {BROWSER}")
        if not name.startswith("VITE_") and KEY_RE.search(value):
            warnings.append(f"frontend/.env {name}: a Google key outside {BROWSER} (not used by the frontend; remove it)")
    for name, value in backend.items():
        if name.startswith("VITE_") and KEY_RE.search(value):
            errors.append(f"backend/.env {name}: browser (VITE_) variables don't belong in the backend")
    if server and browser and server == browser:
        warnings.append("the browser key and the server key are the same key: fine for the demo key, "
                        "but use two keys (each restricted) before real users")
    return errors, warnings


def tracked_key_hits(repo: str = REPO) -> List[str]:
    """file:line of every key-looking string in git-tracked files (the string itself is never returned)."""
    try:
        files = subprocess.run(["git", "ls-files", "-z"], cwd=repo, capture_output=True, check=True).stdout.split(b"\0")
    except Exception:
        return ["(could not list tracked files with git)"]
    hits: List[str] = []
    for raw in files:
        if not raw:
            continue
        rel = raw.decode("utf-8", errors="replace")
        path = os.path.join(repo, rel)
        try:
            if os.path.getsize(path) > 5_000_000:
                continue
            with open(path, encoding="utf-8", errors="ignore") as f:
                for n, line in enumerate(f, 1):
                    if KEY_RE.search(line):
                        hits.append(f"{rel}:{n}")
        except OSError:
            continue
    return hits


def main(argv: List[str]) -> int:
    strict = "--strict" in argv
    errors, warnings = check_envs(parse_env(os.path.join(REPO, "backend", ".env")),
                                  parse_env(os.path.join(REPO, "frontend", ".env")))
    hits = tracked_key_hits()
    errors += [f"key string in a tracked file: {h} (remove it and rotate the key)" for h in hits]
    for w in warnings:
        print(f"WARNING {w}")
    for e in errors:
        print(f"ERROR   {e}")
    failed = bool(errors) or (strict and bool(warnings))
    print(f"\n{'FAILED' if failed else 'OK'}: {len(errors)} error(s), {len(warnings)} warning(s)"
          + (" (--strict: warnings fail)" if strict and warnings else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
