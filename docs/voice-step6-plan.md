# Voice Step 6 — smart actions by voice (weather replan, optimize day, optimize budget)

**Deliverable of this plan:** after approval, the **first** step is to save this document as `docs/voice-step6-plan.md`. Under "Step 6 in detail" in `voicefirst.md`, add one line: "Implementation plan: docs/voice-step6-plan.md". Code comes after that.

## Context
- `voicefirst.md` Step 6: three AI helpers that work by tap should also work by voice. Each asks first and says what changed.
- All Step 6 helpers live in one new module, `voice/tools/smart.py`.
- One thing found in the code changes the spec:
  - **Only `optimize_day_flow_service` writes to the DB.** `weather_replan_service` and `optimize_budget_service` only return `REPLACE_ACTIVITY` suggestions, and the tap modals just display them. Decision: **suggest, then apply on "haan"**. Voice runs the AI before asking, so the question names the real change. On confirm it applies the stored suggestions through the existing `execute_refinement_actions_service`, which already accepts that shape and only touches activities of that trip.

## Reference: how voice tool calling works today
- **Turn:** `voice/ws.py` → `voice/pipeline.py` → `voice/stt.py` (Groq Whisper, no forced language, Hinglish bias prompt) → `voice/agent.py` → `voice/tts.py` (Sarvam `hi-IN`/`en-IN`).
- **Agent** (`agent.py`):
  - One Groq function-calling request. Tool schemas at `:90-225`, prompt at `:41-82`.
  - `_decide` (`:497`) allowlists the tool and runs it in code.
  - user_id and trip_id come from the session and the ownership check, never from the model.
  - A yes/no answer to a pending item is matched by code (`yes_or_no`, `:307`).
- **No translation step.** The LLM reads any language and fills structured, language-neutral args.
  - `lang.py` only yields `hi`/`en`. Other scripts fall back to `hi`, so the user is understood but answered in Hinglish.
  - Step 6 keeps this property: every arg is an enum, int or ISO date, and **code** resolves it.

## 1. Files
| Path | Change |
|---|---|
| `backend/voice/tools/smart.py` (new) | Day resolution, the 3 "propose" functions, `apply_confirmed`, summary builders, sync AI rate-limit check |
| `backend/voice/agent.py` | 3 tool schemas + prompt lines; `_decide` branches; generalize `confirm_trip` → `confirm_pending` (dispatch on `pending["tool"]`); generalize `cancel_trip` → `cancel_pending`; `run_agent` yes/no routing for any pending tool, not only `create_trip`; `clear_memory` unchanged (the same `voice:confirm` key) |
| `backend/voice/ws.py` (`:210-232`) | `confirm`/`cancel` from the button call `confirm_pending`/`cancel_pending`; `ok` = action in `{trip_confirm, smart_applied}` |
| `backend/itinerary_service.py` | Add `ForecastUnavailable` handling stays with callers. Add `try/except: db.rollback(); raise` to `optimize_day_flow_service` and `execute_refinement_actions_service` (both already commit once at the end; make the failure path explicit). Add a new small `set_trip_budget_amount(db, trip_id, amount)` (used only when the budget is missing). Tap behaviour unchanged |
| `frontend/src/voice/uiActions.ts` | New action `refresh` (`what: "itinerary"`), which reloads the current itinerary through TripContext's existing loader. `navigate` to `/itinerary?day=N` already exists |
| `frontend/src/voice/MicButton.tsx` | Run `ui_actions` on `confirm_result` as well (they now carry `refresh` + navigate) |
| `backend/tests/test_voice_step6.py` (new) | See §5 |
| `backend/scripts/eval_smart.py` (new) | ~20 phrases, real Groq, services simulated |
| `docs/voice-step6-plan.md` (new) | This plan |

## 2. Signatures
```python
# voice/tools/smart.py
@dataclass
class DayRef: day_id: str; day_number: int; date: str

def resolve_trip_day(db, trip_id: str, day: str | int | None, today: date) -> DayRef | str
    # "today"/"tomorrow"/"day_after_tomorrow"/YYYY-MM-DD via lookups.resolve_day; int = day number.
    # Returns an error code: "no_itinerary" | "outside_trip" | "need_day"

def propose_weather_replan(user_id, trip, day, lang, redis_conn, conversation_id, db=None) -> AgentResult
def propose_optimize_day(user_id, trip, day, goal, lang, redis_conn, conversation_id, db=None) -> AgentResult
def propose_optimize_budget(user_id, trip, budget_inr, lang, redis_conn, conversation_id, db=None) -> AgentResult
def apply_confirmed(pending: dict, user_id: str, lang: str, db=None) -> AgentResult   # action "smart_applied" | "smart_failed"
def summarize_replacements(actions: list[dict], lang) -> str        # "Amber Fort ki jagah City Palace Museum."
def summarize_day_order(activities: list[dict], day_number, lang) -> str
def check_ai_rate_limit(user_id: str) -> bool   # same Redis key as /ws/app: rl:ws:ai_trip:{user}, 10/min

# voice/agent.py
def confirm_pending(redis_conn, user_id, conversation_id, lang, pending_id=None) -> AgentResult
def cancel_pending(redis_conn, user_id, conversation_id, lang) -> AgentResult
```
**Tool schemas** (all args nullable, like the existing ones):
- `weather_replan(day?: "today"|"tomorrow"|"day_after_tomorrow"|YYYY-MM-DD|int)`
- `optimize_day(day?: same, goal?: enum MINIMIZE_TRAVEL_TIME|RELAXED|MORE_SIGHTS)`
- `optimize_budget(budget_inr?: number)`. `budget_inr` is used only when the user states one in reply to "pehle budget batayein".

**Pending data** (`pending.save(..., tool=<name>, data=...)`): `{trip_id, day_id?, goal?, actions?}`. `actions` holds only the replace items the AI suggested, capped at 5.

## 3. Data flow
**Ask turn:**
1. Groq picks the tool. `_decide` checks there is an open trip (`trip.id` from `ws._resolve_trip`, already ownership-checked). With no trip, it says "Pehle trip kholiye" and navigates to my_trips.
2. `smart.propose_*`:
   - `require_owned_trip`, then `resolve_trip_day`.
   - **weather:**
     - `get_trip_forecast` (read-only). `ForecastUnavailable` → spoken line, no pending.
     - Filter `badWeatherDates` to the resolved day (or the whole trip when no day is given). None → "Kal mausam theek hai, plan badalne ki zaroorat nahi." with no pending and no AI call.
     - Otherwise: rate limit → `weather_replan_service(db, trip_id, forecast_override=forecast)` → keep only the suggestions on the bad days. Zero suggestions → "Baarish hai, par sab jagah indoor hain."
     - Else pending: "{date} {condition} ka forecast hai. {summary} kar doon?"
   - **optimize_day:** pending from a template: "Day 2 ka order travel kam karne ke liye badal doon?" No AI call yet, because the service both computes and writes.
   - **budget:**
     - No `targetAmount` and no `budget_inr` → "Pehle budget batayein, kitna hai?" with no pending.
     - `budget_inr` given (≥ ₹1,000, the draft rule) → `set_trip_budget_amount`.
     - Then rate limit → `optimize_budget_service`. No suggestions or `savingsRequired == 0` → "Plan pehle se budget mein hai."
     - Else pending: "₹X bachane ke liye {summary} kar doon?"
3. The reply carries `pending_confirmation {id, summary}`, so the existing `ConfirmCard.tsx` shows.

**Confirm** (voice "haan" matched by code, or the Confirm button → `ws.py`):
1. `confirm_pending` → `P.take` (once).
2. Dispatch:
   - `create_trip` → existing path.
   - Smart tools → `smart.apply_confirmed`:
     1. `require_owned_trip` again.
     2. Apply: `execute_refinement_actions_service(trip_id, actions)` for weather/budget; rate limit + `optimize_day_flow_service` for optimize_day.
     3. Reply with the summary sentence and `ui_actions: [{type:"refresh", what:"itinerary"}, {type:"navigate", to:"/itinerary?day=N"}]`.

**Cancel:** "nahi" or the Cancel button → `cancel_pending` clears the pending item (it deletes the draft only when the tool is `create_trip`). A new topic cancels it (existing `run_agent:634`). After 5 minutes it expires (existing TTL).

## 4. Edge cases / failures
- No open trip; trip has no itinerary yet (still generating) → "Itinerary abhi ban rahi hai."
- Day outside the trip → "Trip 15 se 18 December tak hai, kaunsa din?" No pending.
- The trip is more than 16 days away, or Open-Meteo is down → `ForecastUnavailable`, and its line is spoken.
- AI rate limit hit → "Thodi der baad try karein." Nothing pending.
- AI service raises (`RuntimeError AI_GENERATION_ERROR`, timeout) → "Abhi plan badal nahi paaya, thodi der mein try karein." The DB was rolled back.
- **Stale suggestions:** an activity deleted between ask and confirm is skipped by `execute_refinement_actions_service`, which only touches that trip's IDs. If 0 were applied → "Plan pehle hi badal gaya tha, kuch nahi badla."
- The confirm is sent twice → the second finds nothing (`P.take`).
- Another user's pending ID → not found (keyed by session user).
- `REMOVE_ACTIVITY` from the AI is **filtered out** of the stored actions. Voice only replaces, it never deletes (voicefirst rule).
- Non-Hindi/English speech → args are still structured. Replies use templates in `hi`/`en` as today.
- Latency: the ask turn for weather/budget includes an AI call (several seconds). v1 has no interim spoken line; the mic stays in "thinking". See the open questions.

## 5. Tests — `backend/tests/test_voice_step6.py` (Groq, Open-Meteo and AI provider simulated, like step 4)
- **Day resolution:** today/tomorrow/ISO/day number → the right `day_id`; outside the trip → a question; no itinerary → a line.
- **Weather:**
  - The forecast is read before any AI call.
  - No bad weather → no pending and no AI call.
  - Far-off trip → `ForecastUnavailable` line.
  - Bad weather → pending holds only the bad-day suggestions, and `REMOVE_ACTIVITY` is filtered out.
- **Optimize day:** pending without an AI call; confirm runs the service once and only on the user's trip; the summary is built from the returned activities.
- **Budget:** missing budget → asks; `budget_inr` then saves it and proposes; already in budget → no pending.
- **Confirm:**
  - Voice "haan" and the button take the same path.
  - A second confirm does nothing.
  - Another user's pending is refused (also over the socket).
  - Ownership is re-checked (the trip deleted in between → refused).
- **Failure:** the service raises → trip activities unchanged (DB assert), and the failure line is spoken.
- **Stale:** an activity deleted before confirm → skipped, and the line is honest.
- **Cancel:** nahi, the Cancel button, or a new topic → nothing applied, and a step 4 draft (if any) is untouched.
- **Rate limit:** the shared `ai_trip` bucket blocks the 11th call within a minute.
- **Logs:** action/step/timings only, with no user words or place names.
- **Regression:** all earlier voice test files still pass unchanged (step 4's create_trip confirm via `confirm_pending`).

**Eval** `backend/scripts/eval_smart.py`: about 20 phrases (Hinglish, English, a couple in Hindi script, one Tamil/Bengali sanity check) → the expected tool + args. Target ≥ 90%. Rerun the step 2/3/4 evals.

## 6. Implementation order
1. Save this plan to `docs/voice-step6-plan.md` and link it from `voicefirst.md`.
2. `itinerary_service.py` rollback hardening + `set_trip_budget_amount`. Run the existing tests.
3. `voice/tools/smart.py`: `resolve_trip_day` + summaries + rate limit (unit tests first).
4. The `propose_*` functions + `apply_confirmed`.
5. `agent.py`: schemas, prompt, `_decide`, `confirm_pending`/`cancel_pending`, `run_agent` routing. (Depends on 3–4.)
6. `ws.py` button path. (Depends on 5.)
7. Frontend `refresh` action + ui_actions on `confirm_result`.
8. `test_voice_step6.py`, then `eval_smart.py`. Run the full voice regression.
9. Add Step 6 notes to `voicefirst.md` (same style as the Step 4 notes), plus an owner test script.

## 7. Verification
```
cd backend
venv/Scripts/python -m pytest tests/test_voice_step6.py -q
venv/Scripts/python -m pytest tests -q -k "voice or ownership or step0"     # regression
venv/Scripts/python -m scripts.eval_smart          # real Groq, ≥ 90%
venv/Scripts/python -m scripts.eval_create_trip    # still ≥ 14/15
cd ../frontend && npm run build && npm run lint
```
**Manual test on an owned trip within 16 days:**
- "kal ka plan mausam ke hisaab se karo" → either "no change" or a concrete question; then "haan" → the itinerary refreshes on that day.
- "day 2 optimize karo" → "haan".
- "budget mein fit karo" on a trip without a budget → it asks, "50 hazaar" → it proposes → Cancel → nothing changed.

## 8. Open questions / assumptions (please confirm)
1. **Interim line:** the spec wants "Plan badal raha hoon, ek minute…" spoken at once, then the result. That needs a new socket message (`progress`) and the frontend playing two clips. Assumption: **skip in v1** and leave it to Step 7 (speed). OK?
2. **Weather scope without a day** ("plan mausam ke hisaab se badlo"): assume the whole trip's bad days. With a day, only that day.
3. **Budget setter:** a tiny `set_trip_budget_amount` in `itinerary_service.py`. OK?
4. **AI cost on "no":** weather/budget spend one AI call even if the user then says no (accepted with the "suggest, then apply" choice).
5. **Tap modals** stay display-only. Adding an Apply button for tap users is out of scope.
6. **Mock provider:** `generate_weather_replan` (mock) flags by keywords only. Real Gemini quality isn't evaluated here (services are simulated in eval).
