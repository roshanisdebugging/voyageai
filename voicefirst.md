# Voice-First VoyageAI — Plan v2

Nov 12, 2026

> **Instructions for whoever builds this (human or AI):**
>
> 1. Build **Step 0 only** (0a → 0b → 0c → 0d). Tick each box in section 3 as it's finished.
> 2. **Stop when Step 0 is complete.** Mark Step 0 as **DONE** here, with the date. Do not start any voice work.
> 3. Voice work (steps 1–7) starts only when the owner says **"start on voice"**. At that point, read this file, `voicefirst.md` in the repo root, first, and follow it from step 1.
>
> **Step 0 status:** DONE — 12 Nov 2026 (branch `step0`). Code complete and tested with scripts; two things still need the owner: a Groq API key in `backend/.env`, and a click-through in the browser. See "Step 0 notes" below.

## Summary

VoyageAI gets a mic button. The user speaks, the server collects what it needs, and the app jumps to an editable review page. Nothing is saved until the user taps Proceed or says "haan".

Voice work starts only after **Step 0** is done. Step 0 fixes security holes in the WebSocket actions, the hard-coded budget and the missing starting city. It also builds the non-voice features voice depends on, and moves AI calls from Gemini to Groq.

Status: plan agreed section by section on 12 Nov 2026. Nothing is built yet. Checked against the `main` branch of `roshanisdebugging/voyageai` (last commit 6 Nov 2026).

## 1. What we are building

One small floating mic button, visible on every page after login. There is no separate Voice mode and no toggle. Tapping works exactly as today.

- **Tap to start, tap to stop.** Up to 30 seconds per recording. Tapping while the app is speaking stops the reply and starts listening.
- **Example:** "Delhi se Jaipur jaana hai 3 din ke liye, budget 20 hazaar."
- **The server collects first, then jumps.** It asks by voice for anything missing. When everything is in, the app opens the final page already filled.
- **The final page is the safety check.** It shows every detail (city, dates, travellers, budget). Everything on it is editable. The user taps Proceed or says "haan".
- **Small actions just happen,** with an Undo toast: save/unsave a place, mark an activity done, change a filter. Undo is by tap only.
- **Big actions ask first:** create trip, add expense, swap activity, regenerate itinerary, and later weather replan, optimize day and optimize budget.
- **Voice never deletes a trip.** It opens the trip and says the user must delete it themselves, at their own risk.
- **Replies are a short spoken summary;** details stay on screen. The spoken text and the audio arrive together. The app shows no captions and not what it heard, only a listening/speaking animation.
- **Language:** the reply matches the user's language (Hindi, English or Hinglish).
- **Off-topic requests** ("tell me a joke") are declined calmly.
- **Platform:** mobile web app.

## 2. What exists today (checked against the repo)

Updated 12 Nov 2026 after Step 0. The table first described the 6 Nov code; rows marked *(Step 0)* changed since.

| Piece | Where | State | Use for voice |
| --- | --- | --- | --- |
| Text-to-speech, Sarvam `bulbul:v3`, Redis cache, default voice `ritu` | `backend/tts_service.py` | Exists | Speak every reply |
| Play base64 audio | `src/hooks/useAudioGuide.ts` | Exists | Play replies |
| One WebSocket, ~40 actions | `src/services/wsClient.ts`, `process_ws_action` in `backend/main.py` | Exists | Carry voice turns |
| Trip creation | `backend/trip_lifecycle.py` `create_trip_for_user`, used by WebSocket and REST | Exists *(Step 0)* | The agent's `create_trip` calls it |
| Ownership check | `backend/ownership.py`; every WebSocket trip action checked before it runs | Exists *(Step 0)* | Every agent tool goes through it |
| Rate limits | `rate_limiter.py`; `WS_RATE_LIMITS` in `main.py` for WebSocket actions | Exists *(Step 0)* | Add a `voice` bucket |
| Budget | `budget: {level, targetAmount}`; amount is what the user gave, level worked out from it | Exists *(Step 0)* | Agent collects the amount |
| Travellers | `adultsCount` / `childrenCount` on create; travellers saved as `ADULT` / `CHILD` | Exists *(Step 0)* | Agent asks adults and children |
| Itinerary download | `/api/trips/{id}/pdf` and Print/PDF in `ItineraryView.tsx` | Exists, owner only *(Step 0)* | "Ready" notice links here |
| Saved places | REST `/api/user/saved-places` | Exists | Small action with Undo |
| Mark activity done | WebSocket `trips:set_activity_done`, button on each activity, Undo toast | Exists *(Step 0)* | `mark_activity_done` tool |
| Tour guide chat | `tour_guide_service.py`, Gemini with Google Search grounding | Exists | Stays on Gemini |
| Other AI calls | `ai_provider.py` (`AI_PROVIDER=groq`), `complete_json()`, `cost_guard.py` | Groq first, Gemini backup *(Step 0)* | Agent uses Groq too |
| Cost guard | `backend/cost_guard.py` | Exists | Not used for voice: the agent declines off-topic requests itself |
| Place search, geocoding | `places.py`, `services/google_maps_service.py` | Exists | "Jaipur" to a real place |
| Starting city | `cities` table (`models_place.py`), `trips.origin_city_id`; looked up, created if missing | Exists *(Step 0)* | Agent fills `origin` |
| Trip review page | Step 6 of `TripCreationWizard.tsx`; opens pre-filled from `navigate('/trips/new', { state: { prefill } })` | Exists *(Step 0)* | The voice "jump" target |
| Undo toast | `src/components/common/UndoToast.tsx` (`useToast().showToast({ message, undo })`) | Exists *(Step 0)* | Small voice actions use it |
| Itinerary-ready notice | `src/components/trip/ItineraryReadyNotice.tsx` | Exists *(Step 0)* | Spoken version in voice |
| Weather | `backend/weather_service.py` (Open-Meteo, real forecast, 16 days ahead) | Exists *(Step 0)* | `weather_replan` tool |

Missing for voice: speech-to-text, mic recording, the agent, and a way for the server to tell the app which page to open.

## 3. Step 0: everything before voice

Everything that isn't voice-specific is done first, in order 0a, 0b, 0c, 0d. Security comes first because those holes are live now.

### 0a. Security

13 WebSocket trip actions have no login check and no ownership check. Anyone connected can read or change any trip by its ID. `regenerate_itinerary` and the optimize actions also spend paid AI calls.

- [x] Login and ownership check on: `get_itinerary`, `get_stays`, `add_stay`, `get_transports`, `add_transport`, `get_expenses`, `add_expense`, `weather_replan`, `optimize_day`, `optimize_budget`, `refine`, `regenerate_itinerary`, `swap_activity`
- [x] Fix `trips:delete`: today it deletes the itinerary, stays, transports and expenses of any trip ID; only the trip row is checked
- [x] Ownership check on the download endpoint `/api/trips/{id}/pdf`, which today accepts guests
- [x] Rate limits on WebSocket actions, strictest on the ones that cost AI money
- [x] Keep one `verify_trip_ownership()` (it is defined twice)
- [x] Remove the dead second `ai:concierge` handler (~line 1681), which never runs

Done when: another user's trip ID is refused on every action.

### 0b. Data

- [x] Save the budget amount the user gives (₹30k, ₹45k, ₹60k…); remove both hard-coded 30000s
- [x] Work out the budget level automatically from amount ÷ days ÷ people, so existing itinerary prompts keep working; the user never sees the level
- [x] Add `origin` (starting city) to trips as a real place; if the city is not in the table, create it
- [x] One shared trip-creation function used by both the WebSocket and REST paths

Done when: a trip created with ₹45,000 and "from Delhi" reads back with both.

### 0c. Screens and features (tap users benefit too)

- [x] Trip review page: every detail shown and editable on the same page, with a Proceed button
- [x] Trip wizard accepts pre-filled values
- [x] Travellers entered as adults and children
- [x] Mark activity done, with Undo
- [x] Undo toast for small actions (save/unsave place, mark done, filters)
- [x] In-app "itinerary ready" notification: "Your itinerary is ready to download. Shall I take you to the page?"
- [x] Itinerary generation suggests transport (train, flight, bus) from the starting city; the AI chooses based on budget
- [x] Check weather replan, optimize day and optimize budget work end to end by tap

Done when: all of the above work by tapping, with no voice.

### 0d. AI provider switch

- [x] Move all AI calls from Gemini to Groq (e.g. `gpt-oss-120b`) through one provider setting in `ai_provider.py`
- [x] Tour guide chat stays on Gemini, for Google Search grounding and Maps-checked places
- [x] Keep Gemini as a backup if Groq fails or hits its limit

Known limit: Groq's free tier allows about 8,000 tokens per minute for the whole account, roughly one itinerary per minute across all users. That's accepted for testing; itinerary generation will need the paid tier first.

### Step 0 notes (12 Nov 2026)

**How each item was built**

- **0a:**
  - Most of it was already on `main` from the 12 Nov security commit.
  - Step 0 added `trips:set_activity_done` to the checked actions.
  - A test confirms that all 14 trip actions refuse another user's trip and require login.
- **Budget level:** worked out as amount ÷ days ÷ people.
  - A child counts as half a person.
  - Per person per day: under ₹2,500 → BUDGET; under ₹6,000 → MODERATE; under ₹12,000 → PREMIUM; above that → LUXURY.
  - Example: ₹45,000 for 3 days, 2 adults and 2 children → ₹5,000 → MODERATE.
  - A trip created with no amount keeps the level it was given. Budget optimize then asks the user to add an amount instead of inventing ₹30,000.
- **Starting city:**
  - Stored once in the new `cities` table and reused by every trip that starts there.
  - India only, like destinations.
- **Transport suggestions:**
  - Asked for in the itinerary prompt when a starting city is known, using the real budget and the group size.
  - Saved as transport with status `RECOMMENDED`, and shown under "Getting there" on the itinerary page.
  - The itinerary cache key now includes the starting city.
- **Weather replan:**
  - Used to run on a made-up "Monsoon Heavy Downpour" forecast. It now uses a real Open-Meteo forecast.
  - For trips more than 16 days away, it says the forecast isn't available yet.
  - With no bad weather, it says so and changes nothing.
- **Groq:**
  - `AI_PROVIDER=groq` is now the default: Groq first (`GROQ_MODEL`, default `openai/gpt-oss-120b`), with Gemini as the backup on any error or rate limit. Mock data is never used as a backup.
  - The cost guard follows the same Groq-then-Gemini order and still fails closed.
  - Swap options and destination highlights now go through `complete_json()`.

**Tested**

- **`step0_test.py` (27 checks):**
  - Two users.
  - Budget, level, starting city (reused, not duplicated), adults and children.
  - Transport suggestion saved; mark done and undo.
  - Another user refused on all 14 trip actions.
  - Optimize day and budget work.
  - Weather says "not yet" for far-off trips.
  - Groq → Gemini fallback with simulated responses.
  - Cost guard fails closed.
- **Earlier ownership test:** 21/21.
- **Rate-limiter tests:** pass.
- **Weather:** a live forecast call for Jaipur works.
- **Frontend:** builds with no type errors.

**Not tested yet (needs the owner)**

1. **Live Groq.** `backend/.env` has `AI_PROVIDER=groq` and an empty `GROQ_API_KEY=`. Until a key is added, every AI call goes to Gemini, so nothing breaks.
2. **The new screens in a browser:** wizard steps, review page, mark done + Undo, save/unsave + Undo, the ready notice and "Getting there".
3. **Real Postgres.**
   - New columns are added at startup (`trips.origin_city_id`, `itinerary_activities.is_done`, `cities` table) with `ADD COLUMN IF NOT EXISTS`. This ran on SQLite only.
   - Check the server log for `[DATABASE INIT]` on first start.

**Not changed (outside Step 0)**

- The food sheet's save button (`toggleSavePlace` in `AppContext.tsx`) still only saves inside the browser session, not on the server.
- `AppContext.activeTrip` still starts from the demo Goa trip in `src/data/mockData.ts`, then overrides it with the real trip. Its budget total and amount spent are now real (the budget amount and logged expenses), but other demo fields may still show.

## 4. How one voice turn works

The backend decides and the app only shows. All rules (login, ownership, limits, validation) stay on the server.

1. **Record.** The user taps the mic. The browser records until the second tap, or until 30 seconds. Android gives `webm/opus`, iPhone Safari gives `mp4/aac`; the server accepts both. The mic needs HTTPS.
2. **Send** over the existing `/ws/app` as action `voice:turn`, with `{ audio_base64, mime, conversation_id, screen }`.
3. **Speech to text:** Groq Whisper. The provider can be swapped to Sarvam or xAI with one setting.
4. **Agent:** a Groq model reads the text, the conversation memory and the current screen, then picks tools (section 5).
5. **Tools run.** Safe and small ones run now. Big ones become a pending action waiting for "haan" or Proceed.
6. **Reply to speech:** Sarvam TTS, voice `ritu`, in the user's language.
7. **Reply to the app** in one message: `{ reply_text, reply_audio_base64, ui_actions, pending_confirmation }`. Text and audio arrive together.
8. **App:** shows the speaking animation, plays the audio, and runs the `ui_actions` (change page, open the filled review page, show the confirm card or the Undo toast).

During trip creation, most turns send no `ui_actions`. The server keeps a **draft trip** in Redis and fills it turn by turn. Only the final turn sends one action: "open the filled review page". If the user leaves midway, the draft and the conversation are thrown away.

For testing, a **developer-only transcript view** shows what was heard. It is visible only to the developer account, shown live and never saved.

## 5. The agent and its tools

The agent is a Groq model with function calling. It never touches the database. It can only call the tools below, and each tool runs as the logged-in user through the ownership check.

| Tool | Group | Behaviour | Voice step |
| --- | --- | --- | --- |
| `navigate(page)`: Home, Trip, Itinerary, Map, Food, Rides, Expenses, Explore, Guide, Saved places, My trips | Look and move | Runs now | 2 |
| `list_my_trips()`, `open_trip(trip)`, `show_itinerary(day?)` | Look and move | Runs now | 2 |
| `search_places(query, near?)` | Look and move | Runs now | 2 |
| `answer_question(question)` | Look and move | Runs now; the Groq agent answers travel questions itself | 3 |
| `update_trip_draft(fields)` | Collect | Fills the server draft; jumps to the review page when complete | 4 |
| `create_trip(...)` | Big | Waits for Proceed or "haan" | 4 |
| `save_place`, `unsave_place`, `mark_activity_done`, `set_filter` | Small | Runs now, Undo toast | 5 |
| `add_expense(trip, title, amount, category)` | Big | Asks first | 5 |
| `swap_activity(activity, replacement)` | Big | Asks first | 5 |
| `regenerate_itinerary(trip)` | Big | Asks first (costs an AI call) | 5 |
| `delete_trip` | Not a tool | Opens the trip; says the user must delete it themselves, at their own risk | 5 |
| `weather_replan`, `optimize_day`, `optimize_budget` | Big | Ask first | 6 |
| `add_stay`, `add_transport`, `refine` | Big | Ask first | Later |

**How confirmation works (enforced on the server):**

1. The agent calls a big tool. The server does **not** run it. It saves a pending action in Redis (expires after 5 minutes) and replies with a summary.
2. The user says "haan"/"yes" or taps Proceed/Confirm. Only then does the confirm handler run the real function.
3. "No", a new topic or the 5-minute expiry cancels it.

The agent cannot skip step 2: the real function is only ever called from the confirm handler.

**When a request is unclear,** the agent asks. Example: two Goa trips gets "the March one or the December one?". A place name that could mean more than one place gets the same treatment.

## 6. Create-trip conversation

The user stays where they are while the agent asks. The app jumps once, to the filled review page, after the date has been said back and confirmed.

| Who | Says | On screen |
| --- | --- | --- |
| User | "Delhi se Jaipur jaana hai 3 din ke liye, budget 20 hazaar" | Listening animation |
| App | "Jaipur for 3 days. Kab se jaana hai, aur kitne adults aur kitne bachche?" | Speaking animation |
| User | "Agle Friday se, 2 adults aur 2 bachche" | Listening animation |
| App | "14 November, Friday se, sahi hai?" | Speaking animation |
| User | "Haan" | Listening animation |
| App | "Done, details check karke Proceed dabaiye." | Jumps to the filled, editable review page |
| User | Taps Proceed or says "haan" | Trip created, itinerary starts generating |
| App (later) | In-app notice: "Your itinerary is ready to download. Shall I take you to the page?" | On "haan", opens the download page |

**Required before the jump:** destination, start date (said back and confirmed), number of days or end date, adults and children, budget amount.

**Optional:** starting city, travel style. If the starting city is given, itinerary generation suggests transport that fits the budget. Anything missing comes from the user's saved preferences.

## 7. Voice changes by area

Only voice-specific work is listed here; everything else is in Step 0.

**Backend**

1. `voice:turn` WebSocket action: login required, audio capped at 30 seconds / 1 MB, its own rate limit.
2. `voice_service.py`: speech-to-text behind a swappable provider (Groq Whisper by default; Sarvam or xAI by setting). Returns the transcript and the detected language.
3. `voice_agent.py`: the Groq function-calling loop, the tool definitions, and conversation memory in Redis (last ~10 turns, 30-minute expiry, cleared when the user leaves midway).
4. Trip draft in Redis, filled turn by turn.
5. Pending actions in Redis (5-minute expiry), plus `voice:confirm` and `voice:cancel` for the tap path.
6. Place lookup: "Jaipur" becomes a real place with existing place search; the agent asks if the name is ambiguous.

**Frontend**

1. Floating mic button on every page, after login only.
2. `useVoiceRecorder`: mic permission, MediaRecorder, `webm` or `mp4`, 30-second cap.
3. Listening and speaking animations.
4. Voice client: sends `voice:turn` and plays the reply. Tapping during playback stops it and starts recording.
5. UI action runner: change page, open the filled review page, show the confirm card and the Undo toast.
6. Developer-only transcript view.

**Removed from the first plan:** the Normal/Voice toggle, and captions for users.

## 8. Build order

Each step works and can be tested on its own. We review after every step before starting the next.

| Step | Delivers | Done when |
| --- | --- | --- |
| 0a. Security | Login and ownership checks on all WebSocket trip actions and the download; WebSocket rate limits | Another user's trip ID is refused everywhere |
| 0b. Data | Real budget amount, level worked out from it; `origin`; one trip-creation function | ₹45,000 and "from Delhi" read back correctly |
| 0c. Screens | Editable review page, adults/children, mark done, Undo, ready notice, transport suggestions | All work by tap |
| 0d. AI switch | Groq everywhere except tour guide chat; Gemini as backup | Itinerary, swap and optimize work on Groq |
| 1. Voice loop | Tap mic, Groq transcribes, Sarvam speaks a reply | Hindi, English and Hinglish heard correctly (developer view) |
| 2. Navigation | "Open my itinerary", "food dikhao" | Every page reachable by voice |
| 3. Questions | "Amber Fort kab jaana best hai?" | Short spoken answer |
| 4. Create trip | Collect, confirm date, review page, Proceed | Nothing created without Proceed or "haan" |
| 5. More actions | Small actions with Undo; expense, swap, regenerate with confirmation; delete redirects | Each behaves as decided; other users' trips untouchable |
| 6. Smart actions | Weather replan, optimize day, optimize budget | Work on own trip only, after confirmation |
| 7. Polish | Speed, error messages, interrupting, voice choice in settings | Reply heard in under ~3 seconds |
| Later | Add stay, add transport, refine | Not scheduled |

## 9. Cost, speed and safety

While testing, the only paid part of a voice turn is the spoken reply: about 30 paise for a 100-character reply on Bulbul v3.

| Part | Provider | Cost while testing |
| --- | --- | --- |
| Speech to text | Groq Whisper | Free: 20 requests/min, 2,000/day ([limits](https://www.grizzlypeaksoftware.com/articles/p/groq-api-free-tier-limits-in-2026-what-you-actually-get-uwysd6mb)) |
| Agent, 1–2 calls | Groq `gpt-oss-120b` | Free: 30 requests/min, 1,000/day, 8K tokens/min ([limits](https://www.developersdigest.tech/models/free-api/groq)) |
| Spoken reply | Sarvam Bulbul v3 | ₹30 per 10,000 characters; v2 is ₹15 ([pricing](https://sarvam.ai/api-pricing)); repeated lines are cached in Redis |

**Capacity:** Groq's free limits apply to the whole account, not per user. All users together get roughly 15–20 voice turns per minute, shared with itinerary generation. That's accepted for testing; the paid tier comes before real users.

**Limits per user:** 15 voice turns per minute and 100 per day.

**Speed target:** under ~3 seconds from the second tap to hearing the reply. Sarvam TTS is likely the slowest part; measure it in step 1.

**Safety:**

- Every tool runs as the logged-in user and passes the ownership check (after Step 0a).
- Big actions need confirmation, enforced on the server.
- Voice cannot delete trips.
- Audio is never stored.
- The developer transcript is shown live and never saved.
- Logs keep tool names and outcomes, not the user's words.

## 10. Decisions

All open questions from the first plan are closed. The only item left for later is letting users choose the reply voice.

| # | Question | Decision |
| --- | --- | --- |
| D1 | Languages | Hindi, English, Hinglish; reply in the language the user spoke |
| D2 | How the mic listens | Tap to start, tap to stop, 30-second cap; tapping during a reply interrupts it |
| D3 | Speech-to-text | Groq Whisper, swappable to Sarvam or xAI; compare on ~20 real Hinglish clips before launch |
| D4 | What counts as "yes" | Voice "haan"/"yes" or tapping Proceed/Confirm |
| D5 | Off-topic requests | The agent declines calmly; no cost-guard call |
| D6 | Store recordings | Never |
| D7 | Delete by voice | Not allowed; opens the trip and says the user must delete it themselves, at their own risk |
| D8 | Agent model | Groq (`gpt-oss-120b`); the whole app moves from Gemini to Groq except tour guide chat |
| D9 | Reply voice | `ritu` for now; users choose a voice in settings later (step 7) |
| Q1 | Voice before login | No, mic only after login |
| Q2 | Transport from starting city | The AI suggests transport that fits the budget (Step 0c) |
| Q3 | App speaks on its own | In-app notification when the itinerary is ready, offering to open the download page |
| Q4 | Screen while collecting | Listening/speaking animation, then the editable review page |
| – | Small actions | Run immediately, with an Undo toast (tap only) |
| – | Add expense | Asks for confirmation |
| – | Budget | Required by voice; amount saved, level worked out automatically |
| – | Travellers | Adults and children, always asked |
| – | Dates | The agent works out "agle Friday" and says the exact date back for confirmation |
| – | Leaving midway | Draft thrown away |

## Sources

- [Sarvam AI API pricing](https://sarvam.ai/api-pricing)
- [Sarvam pricing (docs)](https://docs.sarvam.ai/api/getting-started/pricing)
- [Groq API free tier limits 2026](https://www.grizzlypeaksoftware.com/articles/p/groq-api-free-tier-limits-in-2026-what-you-actually-get-uwysd6mb)
- [Groq free models and limits](https://www.developersdigest.tech/models/free-api/groq)
- [Groq free tier is per organization](https://klymentiev.com/blog/groq-api-free-tier)
- [xAI speech-to-text docs](https://docs.x.ai/developers/model-capabilities/audio/voice)