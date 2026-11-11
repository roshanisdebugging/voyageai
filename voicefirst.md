# Voice-First VoyageAI — Plan

Status: **draft for review. Nothing in this document is built yet.**
Review each section, mark what's wrong or missing, and we'll change the plan before writing code.

---

## 1. What we are building (my understanding)

- The app gets **two ways to use it**, side by side:
  - **Normal mode:** tap and type, exactly as today.
  - **Voice mode:** press a mic button, speak, and the app does the work.
- In voice mode the user can say things like:
  > "I want to go to Jaipur for 3 days from Delhi, my budget is 20,000 rupees, two people."
- The app then:
  1. Turns the speech into text on **our backend**.
  2. Understands what the user wants.
  3. Asks back, by voice, for anything missing ("When do you want to start?").
  4. **Moves through the app by itself**: opens pages, fills forms, shows results. The user doesn't tap.
  5. Before doing anything that **saves or changes data**, it reads back a summary and asks
     *"Should I confirm?"*. It only acts after the user says yes or taps Confirm.
  6. **Speaks every reply** using Sarvam text-to-speech, sent from the backend to the app.
- Everything a user can do by tapping should eventually be doable by voice.

---

## 2. What already exists that we can reuse

| Piece | Where | Reuse for voice |
|---|---|---|
| Text-to-speech (Sarvam `bulbul:v3`, Indian voices, cached in Redis) | `backend/tts_service.py` | Speak every reply |
| Playing base64 audio in the browser | `src/hooks/useAudioGuide.ts` | Play the reply audio |
| One open WebSocket for everything (`/ws/app`) | `src/services/wsClient.ts`, `process_ws_action` in `backend/main.py` | Carry voice turns, no new connection |
| Safe trip creation (validation, limits, queueing) | `backend/trip_lifecycle.py` | The agent's "create trip" tool |
| Ownership checks | `backend/ownership.py` | Every agent tool that touches a trip |
| Rate limits per WebSocket action | `WS_RATE_LIMITS` in `main.py` | Limit voice turns |
| Cost guard (blocks off-topic messages before paid AI) | `backend/cost_guard.py` | Possibly reused; see Decision D5 |
| Place search / geocoding | `places.py`, `services/google_maps_service.py` | Turn "Jaipur" into coordinates |

**Missing today:**
- Speech-to-text.
- Microphone recording in the browser.
- An "agent" that chooses actions.
- A way for the backend to tell the frontend "go to this page / open this form".
- A **starting city** field on trips. "From Delhi" has nowhere to be saved.
- The **budget amount** the user says is ignored. The backend always saves `targetAmount: 30000`.

---

## 3. How one voice turn works

```
[User holds mic button] ──► browser records audio (MediaRecorder, webm/opus)
[User releases]         ──► send over /ws/app:  action "voice:turn"
                              payload: { audio_base64, mime, conversation_id, screen }

BACKEND
  1. Speech → text         Sarvam speech-to-text           "Jaipur jaana hai 3 din ke liye"
  2. Agent (Gemini)        reads text + conversation memory + current screen,
                           picks tools to call (see section 4)
  3. Run the tools         SAFE tools run now; DATA-CHANGING tools only create
                           a "pending action" that waits for confirmation
  4. Reply text → speech   Sarvam TTS                      "Kab se jaana hai?"

  reply to the app:
  { transcript, reply_text, reply_audio_base64,
    ui_actions: [ {type:"navigate", to:"/trips/new"},
                  {type:"fill_trip_form", fields:{destination:"Jaipur", days:3}} ],
    pending_confirmation: null | { id, summary } }

FRONTEND
  - shows what the user said and the reply as text (captions)
  - plays the reply audio
  - runs ui_actions: change page, open sheet, fill form, show a Confirm card
```

**Why the backend decides and the frontend only shows:** all the rules (who owns what, limits, validation) already live on the backend. The frontend stays simple: it follows `ui_actions`.

---

## 4. The agent and its tools

The agent is Gemini with **function calling**. It can't touch the database or the app directly. It can only call the tools below, and **we** write each tool.

### Safe tools: run immediately, change nothing
| Tool | What it does |
|---|---|
| `navigate(page)` | Go to Home, Trip, Itinerary, Map, Food, Rides, Expenses, Explore, Guide, Saved places, My trips |
| `list_my_trips()` | Read the user's trips |
| `open_trip(trip)` | Make a trip the current one and show it |
| `show_itinerary(day?)` | Open the itinerary, optionally at a day |
| `search_places(query, near?)` | Find places (food, sights) and show them |
| `answer_question(question)` | Travel Q&A, reusing the tour guide chat |
| `fill_trip_form(fields)` | Open the trip wizard and fill what we know so far |

### Data-changing tools: need a "yes" first
| Tool | What it does |
|---|---|
| `create_trip(...)` | Creates the trip and starts itinerary generation, using `trip_lifecycle.create_trip_for_user` |
| `add_expense(trip, title, amount, category)` | Logs an expense |
| `swap_activity(activity, replacement)` | Replaces an activity |
| `delete_trip(trip)` | Deletes a trip (always asks twice?) — see D7 |
| `regenerate_itinerary(trip)` | Makes a new itinerary (costs an AI call) |

### How confirmation works (enforced on the server)
1. The agent calls `create_trip(...)`. The server **doesn't create it**. It saves a *pending action* (in Redis, expires after 5 minutes) and replies:
   *"Jaipur, 10 to 12 January, 2 people, moderate budget. Should I create it?"*
   The app shows a **Confirm / Cancel** card too.
2. The user says **"yes" / "haan"** or taps **Confirm**. Only then does the server run the saved action.
3. "No", silence, a new topic, or the 5-minute expiry cancels it.

The agent can't skip step 2, because the real function is only called from the confirm handler, never from the agent.

---

## 5. Example conversation: create a trip

| Who | Says | What happens on screen |
|---|---|---|
| User | "Mujhe Delhi se Jaipur jaana hai 3 din ke liye, budget 20 hazaar" | Captions show the transcript |
| App | "Great, Jaipur for 3 days. Kab se jaana hai, aur kitne log hain?" | Trip wizard opens with Jaipur and 3 days filled |
| User | "Agle Friday se, hum do log" | Dates and travellers fill in |
| App | "Jaipur, 14 to 16 November, 2 people, around ₹20,000. Should I create this trip?" | Confirm card appears |
| User | "Haan" | Trip is created, itinerary starts generating, page moves to the trip |
| App | "Done! Your itinerary is being prepared, I'll tell you when it's ready." | When the worker finishes, the app speaks "Your Jaipur plan is ready" |

**Information the agent must collect before it can ask to confirm:** destination, start date, end date or number of days, and number of travellers.
**Optional:** starting city, budget amount or level, and travel style. Anything not given comes from the user's saved preferences.

---

## 6. Changes needed, by area

### Backend
1. **`voice:turn` WebSocket action**
   - Accepts the audio.
   - Size limit (for example 30 seconds or 1 MB).
   - Rate limit (bucket `voice`).
   - Login required.
2. **`voice_service.py`:** Sarvam speech-to-text call, returning the transcript and detected language.
3. **`voice_agent.py`:**
   - The Gemini function-calling loop.
   - Tool definitions.
   - Conversation memory per user in Redis (last ~10 turns, 30-minute expiry).
4. **Pending actions:** store, confirm and cancel in Redis. Add `voice:confirm` and `voice:cancel` actions for the tap path.
5. **Trip data gaps:**
   - Add `origin` (starting city) to trips.
   - Actually save the user's budget amount (`customBudgetAmount`) instead of the fixed 30000.
6. **Turning names into places:** "Jaipur" becomes coordinates with existing place search. The agent asks if the name is ambiguous.
7. **"Itinerary ready" spoken notice:** reuse the existing owner-only push, plus a TTS line.

### Frontend
1. **Normal / Voice toggle**, saved per user on the server, not in the browser.
2. **Mic button**: a floating button, visible on every page in Voice mode.
3. **Recorder hook (`useVoiceRecorder`):** microphone permission, MediaRecorder, a recording indicator.
4. **Voice client:** sends `voice:turn`, plays the reply, shows captions.
5. **UI action runner:** one place that turns `ui_actions` into router navigation, opening sheets, filling the wizard, and showing the Confirm card.
6. **Trip wizard accepts pre-filled values**, so voice and taps share the same form.

### Not changing
- Normal mode stays exactly as it is.
- All the existing tap flows keep working.

---

## 7. Build order (each step is usable and testable on its own)

| Step | Delivers | How we check it's done |
|---|---|---|
| 0. Data fixes | `origin` field, budget amount saved | Create a trip with origin and budget, then read it back |
| 1. Voice loop | Hold mic → transcript shown → spoken echo reply. No actions yet. | Speak Hindi and English; the transcript is correct and the reply plays |
| 2. Navigation by voice | "Open my itinerary", "go to food" change the page | Every page in section 4 is reachable by voice |
| 3. Questions by voice | "Best time to visit Amber Fort?" gets a spoken answer | Same answers as the chat |
| 4. Create trip by voice | Full flow from section 5, with confirmation | Trip is created only after "yes"; "no" creates nothing |
| 5. More actions | Expenses, swap activity, regenerate, delete | Each needs confirmation; another user's trip can't be touched |
| 6. Polish | Interrupting, silence detection, barge-in, latency tuning | Turn time target met (see section 8) |

We review after every step before starting the next.

---

## 8. Cost, speed and safety

- **Calls per voice turn:**
  - 1 Sarvam speech-to-text call.
  - 1–2 Gemini calls (more if the agent needs a tool result before answering).
  - 1 Sarvam text-to-speech call.
  - All paid. Rate limit voice turns per user (proposal: 15 per minute).
- **Speed target:** under ~3 seconds from releasing the button to hearing the reply. We'll measure in step 1. To speed things up we can show the text before the audio arrives.
- **Safety:**
  - Every tool runs as the logged-in user and goes through `ownership.py`.
  - Data changes need confirmation enforced on the server.
  - Audio is not stored after transcription (proposal; see D6).
  - Logs keep tool names and outcomes, not the user's words.

---

## 9. Decisions needed from you

Each has my recommendation; change any you disagree with.

| # | Question | Options | Recommendation |
|---|---|---|---|
| D1 | Languages | Hindi + English + Hinglish / English only / many Indian languages | **Hindi + English + Hinglish.** Detect the language each turn and reply in the same one. |
| D2 | How the mic listens | Hold to talk / tap, then auto-stop on silence / both | **Hold to talk first**; add tap-and-auto-stop in step 6 |
| D3 | Where speech-to-text runs | Sarvam / Gemini listens to the audio directly | **Sarvam.** You asked for transcription on our backend, and it's strong on Indian languages. |
| D4 | What counts as "yes" | Voice "yes/haan/confirm" + tap / tap only | **Both voice and tap** |
| D5 | Off-topic voice requests ("tell me a joke") | Reuse cost guard / let the agent politely decline | **Agent declines.** Its instructions keep it on travel, which avoids an extra classification call per turn. |
| D6 | Store recordings? | Never / keep 7 days for debugging | **Never** |
| D7 | Deleting a trip by voice | Allowed with confirmation / tap only | **Tap only** at first. It can't be undone. |
| D8 | Which Gemini model for the agent | Same flash model as today / a stronger model | **Same flash model**; revisit if it picks wrong tools |
| D9 | Voice for replies | Fixed (for example `ritu`) / user chooses in settings | **Fixed at first**, setting later |

---

## 10. Open questions I still have

1. Should Voice mode work **before login** (for example, "what can you do?")? My plan assumes login is required.
2. When the user says "from Delhi", should the app also suggest **transport** (train or flight), or just save the starting city for now?
3. Should the app **speak on its own**, for example "your itinerary is ready", or only reply when spoken to?
4. Is the **trip wizard** the right screen to show while collecting details, or should voice have its own simpler card?
