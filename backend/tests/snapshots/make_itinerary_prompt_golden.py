"""
Writes the golden itinerary prompts (no purpose / leisure) from construct_ai_prompt as it is when this script runs.
Run ONCE from backend/ BEFORE changing the prompt: python -m tests.snapshots.make_itinerary_prompt_golden
tests/test_trip_purpose_plan.py checks that a trip with no purpose, leisure or pilgrimage still gets exactly these.
"""
import os
import sys
from pathlib import Path

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"
BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from tests.snapshots.itinerary_prompt_inputs import GOLDEN_INPUTS  # noqa: E402
import itinerary_service  # noqa: E402

for name, ai_input in GOLDEN_INPUTS.items():
    out = Path(__file__).with_name(f"itinerary_prompt_{name}.txt")
    out.write_text(itinerary_service.construct_ai_prompt(ai_input), encoding="utf-8", newline="\n")
    print(f"wrote {out.name}")
