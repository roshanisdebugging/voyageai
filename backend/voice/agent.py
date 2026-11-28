"""
The voice agent ("the mind"), voicefirst.md steps 2-5 + "Fixes before Step 4".

ONE LLM call per turn decides (retried once on a transient error); tools:
navigate, answer_question, search_places, get_weather, list_my_trips, open_trip, cant_help. Read-only.

transcript + memory + current state -> OpenAI (function calling) -> our code checks the call and runs the tool
(voice/pages.py, voice/tools/lookups.py, tour_guide_service.voice_answer) -> (reply_text, ui_actions, note).
The model never touches data and never supplies a trip ID: trips are looked up by the session's user.
Step 4 adds the trip draft (voice/draft.py); step 5 adds actions on the open trip (voice/tools/actions.py):
small ones run now with an Undo toast, big ones wait for "haan" / Confirm (voice/pending.py), voice never deletes.
"Where is X" answers with city/state and keeps the map actions pending; "haan"/"yes" runs them (no LLM call).
Logs carry the action, timings and error codes only, never the user's words or the reply.

Memory: Redis voice:mem:{user_id}:{conversation_id}, last 10 turns (user + assistant), 30-minute
TTL refreshed each turn, deleted on end_session. Pending map actions: voice:pending:{user}:{conversation}, 2 min.
"""
import json
import logging
import os
import re
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from voice import pages
from voice.lang import detect_lang
from voice.text_utils import canon, is_devanagari_letter, normalize_text as tu_normalize, words as tu_words

logger = logging.getLogger("voice")

MEMORY_TURNS = 10
MEMORY_TTL_SECONDS = 30 * 60
PENDING_TTL_SECONDS = 120
LLM_TIMEOUT_SECONDS = 8
FALLBACK_REPLY = "Abhi samajh nahi paaya, phir se boliye."
# The Hinglish-only lines (FALLBACK_REPLY, UNCLEAR_REPLY) in English, used only when the user chose English as the
# voice language (voice/languages.py). "auto" keeps them in Hinglish as before.
FALLBACK_REPLY_EN = "Sorry, I didn't get that. Please say it again."
UNCLEAR_REPLY_EN = "Sorry, I didn't catch that. Please say it again."
# The AI service is limited or down: say "try again later" (not "I didn't understand"), in the user's language.
TRY_LATER_REPLY = {"hi": "Abhi jawab nahi de paa raha, thodi der baad phir try karein.",
                   "en": "I can't answer right now, please try again in a little while."}

# Garbled words have no reliable language, so "unclear" is always said in Hinglish (fixes-before-step4 item 6).
UNCLEAR_REPLY = {"hi": "Samajh nahi aaya, phir se boliye.", "en": "Samajh nahi aaya, phir se boliye."}
DECLINE_REPLY = {"hi": "Main sirf aapki trip mein madad kar sakta hoon.", "en": "I can only help with your trip."}
OK_NO_REPLY = {"hi": "Theek hai.", "en": "Okay."}
ANSWER_FAILED = {"hi": "Abhi jawab nahi mil paaya, thodi der mein phir poochhiye.",
                 "en": "I couldn't get an answer right now, please ask again in a moment."}

SYSTEM_PROMPT = """You are VoyageAI's voice assistant inside a travel app for Indian users.

How to reply:
- Reply in the language the user spoke: Hinglish in Roman script, Hindi, or English.
- Your reply is spoken aloud: at most 2 short sentences, no lists, no emojis.

Call exactly one tool when it fits:
- navigate: open a page. "Plan a new trip" / "nayi trip banani hai" -> navigate to plan_trip at once,
  do not ask for details. "Itinerary kholo" without a day -> navigate to itinerary, do not ask which day.
- get_weather: ANY weather question (baarish, rain, mausam, temperature, garmi, thand, kal ka mausam).
  Never use answer_question for weather.
- search_nearby: a KIND of place (restaurant, cafe, chai, street food, hotel, ATM, petrol pump, hospital, pharmacy,
  toilet, or anything else as said): "Hawa Mahal ke paas cafe", "Howrah ke paas achha restaurant", "mere aaspas
  khane ki achhi jagah", "near me ATM", "achha restaurant dikhao", "khana kahan milega", "where can I eat".
  category = the kind in English with any quality word ("good restaurant", "cheap hotel", "chai", "street food").
  near = the place the user said for WHERE, as said ("Howrah", "Hawa Mahal", "Park Street", "Baga Beach Goa"); any
  place counts (landmark, area, city, station, hotel). Do NOT add the open trip's city. null if no place was said.
  near_me = true for "mere aaspas", "mere paas", "yahan ke paas", "near me", "nearby", "current location ke paas".
  A kind with no place words ("achha restaurant dikhao", "khana kahan milega") -> near=null, near_me=false; our code
  uses the user's location.
  If the user names BOTH a kind and a place ("X ke paas Y", "Y near X", "X ke aas-paas Y", "X mein Y"), ALWAYS use
  search_nearby, NEVER search_places on the landmark alone.
- The Food page: navigate to food ONLY when the user asks for the page itself ("food page kholo", "food section
  kholo", "open the food page"). Asking where to eat is search_nearby, never navigate.
- search_places: a NAMED place (one specific place, no kind of place asked for).
  * "X kahan hai" / "where is X" -> show=false (we tell them where it is and offer the map).
  * "X dikhao" / "show me X" / "X map pe dikhao" -> show=true (open the map).
  * query = the place's usual written name, fixing speech-to-text spelling: "4 minar" -> "Charminar",
    "taaj mahal" -> "Taj Mahal". If the last reply offered a choice ("A ya B?"), the answer is the place.
  General "ghoomne ki jagah dikhao" / things to do -> navigate to explore instead.
- get_travel_time: how far / how long to a NAMED place ("Hawa Mahal kitni door hai", "airport kitni der
  lagegi bike se", "how far is India Gate"). mode: drive (default, car/cab), two_wheeler (bike/scooty), walk (paidal).
- answer_question: other travel questions (timings, tickets, prices, food, culture, transport, tips).
  Do NOT answer these from memory. Set facts=true for timings, opening hours, prices, entry fees.
  ("Where can I eat" / "khana kahan milega" -> search_nearby, not answer_question.)
- list_my_trips: which trips the user has ("meri trips kaun si hain"); past trips only for purani / past.
- open_trip: open a specific trip by name, destination, month, or next/current/last ("Goa wali trip kholo",
  "agli trip kholo"). If you asked "which one?" and the user answers with a month, call open_trip again.
- cant_help: reason="off_topic" for clear non-travel requests (jokes, cricket, coding, politics);
  reason="unclear" when the words are garbled, nonsense or can't be understood. Don't guess what garbled
  words meant.
- If the request is understandable but unclear (e.g. "woh wala kholo"), ask ONE short question.
- update_trip_draft: the user wants to create a trip by voice and gives details ("Goa jaana hai, 15 se 18
  December, do log", "trip banao Jaipur ke liye"), or answers a question about the trip being planned, or
  corrects a detail ("nahi, budget 50 hazaar kar do"). Pass ONLY values the user said:
  DATES AS SPOKEN: a date the user says with a day number goes in start_day / start_month / start_year (end_day /
  end_month / end_year for the last day), ONLY the parts the user actually SPOKE. Never fill in a month or year you
  assumed: our code picks them. "पच्चीस तारीख से" / "25 tarikh se" / "25th se" -> start_day=25, start_month=null,
  start_year=null. "25 se 27" / "25 से 27 तक" -> start_day=25, end_day=27 (months null). "5 November" ->
  start_day=5, start_month=11, start_year=null. "25 November 2025" -> start_day=25, start_month=11, start_year=2025.
  Then leave start_date / end_date null. Relative dates with no day number ("kal", "parso", "agle Friday", "kal se
  pehle") go in start_date as YYYY-MM-DD from today's date, with the *_day fields null. "3 din ke liye"
  -> days=3; people as integers ("do log" -> adults=2, "koi bachcha nahi" -> children=0); budget in rupees as a
  number ("50 hazaar" -> 50000, "1.5 lakh" -> 150000). origin_city = where the trip STARTS, only when the user
  says it: "Delhi se", "from Delhi", "कोलकाता से गोवा" / "Kolkata se Goa" -> origin_city=Kolkata, destination=Goa.
  "Goa jaana hai" alone -> destination=Goa, NO origin_city. If our last question asked for origin_city, a bare city
  name is the origin_city. A correction at the read-back like "nahi, Patna se" -> origin_city=Patna only.
  "पता" / "pata" alone is NOT a city: it means the user does not know (no origin_city). Never pass "pata",
  "nahi", "kuch", "koi" or "kahin" as origin_city. "pata nahi, Delhi se" -> origin_city=Delhi.
  purpose = WHY they travel, in the user's own words exactly as said ("hackathon ke liye", "kaam se", "bas ghoomna"),
  only when said; our code decides the type. base_area = the area or locality at the destination they will mostly be
  in ("Electronic City mein hackathon hai" -> base_area=Electronic City), only when said. If our last question asked
  for purpose or base_area, the answer is that field.
  start_new=true only when the
  user starts a different new trip while one is being planned. Never ask for details yourself: our code asks.
  A destination alone counts as a detail ("plan a trip to Manali" -> update_trip_draft).
  "Nayi trip banani hai" / "plan a new trip" with NO details at all -> navigate to plan_trip.
- cancel_trip_draft: the user wants to stop planning this trip ("cancel karo", "trip mat banao").
- weather_replan: CHANGE the plan because of the weather ("aaj baarish hai, plan badlo", "kal ka plan mausam ke
  hisaab se karo"). A weather QUESTION is get_weather, never this. day = today | tomorrow | day_after_tomorrow |
  YYYY-MM-DD | the day number as text ("2"); leave it out for the whole trip. "kal" = tomorrow, "parso" =
  day_after_tomorrow (NOT tomorrow). Needs an open trip.
- optimize_day: reorder ONE day ("aaj ka route chhota karo", "day 2 optimize karo"). goal = MINIMIZE_TRAVEL_TIME
  (default), RELAXED ("relaxed karo"), MORE_SIGHTS ("zyada jagah dikhao"). Needs an open trip.
- optimize_budget: make the plan fit the budget ("budget mein fit karo", "kharcha kam karo"). Set budget_inr
  ONLY when the user says an amount, e.g. the answer to "kitna budget hai?" ("50 hazaar" -> 50000).
  While a trip is being planned by voice (see "Trip being planned" below), a budget amount or "budget X kar
  do" is update_trip_draft, NEVER optimize_budget.
- set_trip_budget: SET or CHANGE the open trip's budget amount ("budget 25000 kar do", "budget badal ke 40 hazaar
  rakho", "set budget to 30000", "budget 1.5 lakh rakho"). amount in rupees as a number ("40 hazaar" -> 40000,
  "1.5 lakh" -> 150000). When a trip is OPEN and NO new trip is being planned ("Trip being planned: none"), a budget
  amount is ALWAYS set_trip_budget, NEVER update_trip_draft (that is only for creating a new trip) and never
  optimize_budget ("budget mein fit karo" without a new amount is optimize_budget).
  These four only ask first; our code does the rest. Never say the plan or budget was changed yourself.
Actions on a trip (default: the OPEN trip, its plan is listed below; pass an activity's short ID like "a5" if you
can, else its name). Only if the user names ANOTHER trip ("Goa wali trip mein...", "December wali trip", "agli trip")
set trip_name / trip_month / trip_which (next, current, last); our code finds it.
- mark_activity_done: the user did an activity ("Hawa Mahal done ho gaya", "Amber Fort ho gaya"); done=false to
  unmark it.
- save_place / unsave_place: save or remove a place ("yeh jagah save karo", "Hawa Mahal saved se hatao"). place =
  the name only if the user said one.
- add_expense: money spent on this trip ("auto ka 350 add karo", "khane ka 1200 kharcha"). amount in rupees as a
  number; title short (e.g. "Auto", "Lunch"); category: food, transport, stay, shopping, tickets or other. Our code
  asks the user to confirm.
- swap_activity: replace an activity with something else ("Amber Fort ki jagah kuch aur").
- regenerate_itinerary: rebuild the whole plan ("plan dobara banao"). Our code asks the user to confirm.
- If you can't tell which activity the user means, ask which one. Never guess.
- NEVER delete anything (trips, activities, expenses). For any delete request reply exactly:
  "Trip delete karne ke liye button khud dabaiye, dhyan se."
- Never invent pages, routes, trips, places or facts.
- You cannot add new places to an existing itinerary or rebuild it around a new place or purpose. Never say you are updating the trip yourself. Only the available tools (optimize day, weather replan, swap activity) can change it. If the user asks for something else, say it cannot be done by voice yet.

Current state:
- Today (India): {today}
- User is on page: {screen}
- Open trip: {trip_line}
- Open trip's plan: {trip_context}
- Trip being planned by voice: {draft_line}"""


def _nullable(t: str) -> List[str]:
    # Tool arguments are validated strictly and the model often sends null for "not given".
    return [t, "null"]


NAVIGATE_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "navigate",
        "description": "Open a page of the app. Pages: " + "; ".join(f"{p}: {m}" for p, m in pages.MEANINGS.items()) + ".",
        "parameters": {
            "type": "object",
            "properties": {
                "page": {"type": "string", "enum": pages.PAGES},
                "day": {"type": _nullable("integer"), "minimum": pages.MIN_DAY, "maximum": pages.MAX_DAY,
                        "description": "Only for itinerary: which day to open."},
            },
            "required": ["page"],
        },
    },
}
ANSWER_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "answer_question",
        "description": "Answer a travel question (timings, tickets, prices, food, culture, transport, tips) with the "
                       "tour guide. Not for weather (use get_weather) and not for where a place is (use search_places).",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The user's question, cleaned up, in their language."},
                "place": {"type": _nullable("string"), "description": "The place it is about, if any."},
                "facts": {"type": _nullable("boolean"),
                          "description": "true if it asks for timings, opening hours, prices, entry fees or ticket costs."},
            },
            "required": ["question"],
        },
    },
}
SEARCH_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_places",
        "description": "A named place in India. show=false for 'X kahan hai / where is X' (tell where it is, offer the map); "
                       "show=true for 'X dikhao / show me X' (open the map).",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The place's usual written name, e.g. 'Hawa Mahal Jaipur'; "
                                                            "fix speech-to-text spelling ('4 minar' -> 'Charminar')."},
                "show": {"type": "boolean", "description": "true = open the map now; false = say where it is and ask."},
            },
            "required": ["query", "show"],
        },
    },
}
NEARBY_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_nearby",
        "description": "Places of a kind (restaurant, cafe, chai, street food, hotel, ATM, petrol pump, hospital, pharmacy, "
                       "toilet...) near a place the user named, or around the user. Shows them on the map.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "The kind of place in English, with any quality word: "
                                                               "'good restaurant', 'cafe', 'cheap hotel', 'atm', 'petrol pump'."},
                "near": {"type": _nullable("string"), "description": "The place the user said for where, as said "
                                                                     "('Howrah', 'Hawa Mahal'); null if none."},
                "near_me": {"type": _nullable("boolean"), "description": "true for 'mere aaspas' / 'near me' / 'nearby' / "
                                                                         "'yahan ke paas'."},
            },
            "required": ["category"],
        },
    },
}
WEATHER_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Real weather forecast (rain chance, temperature) for a place and day, up to 16 days ahead. "
                       "Without a place, the open trip's destination is used.",
        "parameters": {
            "type": "object",
            "properties": {
                "place": {"type": _nullable("string"), "description": "City or place, e.g. 'Jaipur'."},
                "day": {"type": _nullable("string"),
                        "description": "today | tomorrow | day_after_tomorrow | a date YYYY-MM-DD. Kal = tomorrow, parso = day_after_tomorrow."},
            },
        },
    },
}
TRAVEL_TIME_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_travel_time",
        "description": "Road distance and travel time from the device's current location (only that; never the trip, "
                       "a hotel or a previous activity) to a named place in India. Read-only.",
        "parameters": {
            "type": "object",
            "properties": {
                "place": {"type": "string", "description": "The place's usual written name, e.g. 'Hawa Mahal Jaipur', 'Jaipur airport'."},
                "mode": {"type": _nullable("string"), "enum": ["drive", "two_wheeler", "walk", None],
                         "description": "drive (car, default) | two_wheeler (bike, scooty) | walk (paidal)."},
            },
            "required": ["place"],
        },
    },
}
LIST_TRIPS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "list_my_trips",
        "description": "Say which trips the user has and open My trips.",
        "parameters": {
            "type": "object",
            "properties": {"include_past": {"type": _nullable("boolean"), "description": "true only if the user asks for past/old (purani) trips."}},
        },
    },
}
OPEN_TRIP_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "open_trip",
        "description": "Open one of the user's own trips, found by name/destination, month, or which (next/current/last).",
        "parameters": {
            "type": "object",
            "properties": {
                "name_or_destination": {"type": _nullable("string"), "description": "Trip name or destination, e.g. 'Goa'."},
                "month": {"type": _nullable("string"), "description": "Month of the trip start, e.g. 'December' or '12'."},
                "which": {"type": _nullable("string"), "enum": ["next", "current", "last", None]},
            },
        },
    },
}
CANT_HELP_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "cant_help",
        "description": "The request can't be handled: off_topic (clear non-travel request) or unclear (garbled / nonsense words).",
        "parameters": {
            "type": "object",
            "properties": {"reason": {"type": "string", "enum": ["off_topic", "unclear"]}},
            "required": ["reason"],
        },
    },
}
UPDATE_DRAFT_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "update_trip_draft",
        "description": "Create a trip by voice: save the trip details the user said (any subset). Our code checks them, "
                       "decides what is still missing and asks for it.",
        "parameters": {
            "type": "object",
            "properties": {
                "destination": {"type": _nullable("string"), "description": "Where to go, e.g. 'Jaipur'."},
                "origin_city": {"type": _nullable("string"), "description": "Starting city, e.g. 'Delhi'."},
                "start_date": {"type": _nullable("string"), "description": "YYYY-MM-DD, only for relative dates (kal, agle Friday)."},
                "end_date": {"type": _nullable("string"), "description": "YYYY-MM-DD (last day of the trip), only for relative dates."},
                "start_day": {"type": _nullable("integer"), "description": "Day of month AS SPOKEN (1-31)."},
                "start_month": {"type": _nullable("integer"), "description": "Month 1-12 ONLY if the user said it, else null."},
                "start_year": {"type": _nullable("integer"), "description": "Year ONLY if the user said it, else null."},
                "end_day": {"type": _nullable("integer"), "description": "Last day's day of month AS SPOKEN."},
                "end_month": {"type": _nullable("integer"), "description": "Month 1-12 ONLY if the user said it, else null."},
                "end_year": {"type": _nullable("integer"), "description": "Year ONLY if the user said it, else null."},
                "days": {"type": _nullable("integer"), "description": "Trip length in days, if said instead of an end date."},
                "adults": {"type": _nullable("integer")},
                "children": {"type": _nullable("integer")},
                "budget_inr": {"type": _nullable("number"), "description": "Total budget in rupees."},
                "purpose": {"type": _nullable("string"), "description": "WHY the user travels, in their own words as "
                            "said (e.g. 'hackathon ke liye', 'kaam se', 'bas ghoomna'). Only if said."},
                "base_area": {"type": _nullable("string"), "description": "The area or locality at the destination the "
                              "user will mostly be in (e.g. 'Electronic City'). Only if said."},
                "start_new": {"type": _nullable("boolean"), "description": "true only for a different new trip while one is being planned."},
            },
        },
    },
}
CANCEL_DRAFT_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "cancel_trip_draft",
        "description": "Stop planning the trip being created by voice; nothing is saved.",
        "parameters": {"type": "object", "properties": {}},
    },
}
def _fn(name: str, description: str, properties: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    params: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        params["required"] = required
    return {"type": "function", "function": {"name": name, "description": description, "parameters": params}}


ACTIVITY_ARG = {"type": "string", "description": "The activity's short ID from the plan (e.g. 'a5') or its name."}
TRIP_ARGS = {
    "trip_name": {"type": _nullable("string"), "description": "Only if the user names a trip: its name/destination, e.g. 'Goa'."},
    "trip_month": {"type": _nullable("string"), "description": "Only if the user names a trip by month, e.g. 'December'."},
    "trip_which": {"type": _nullable("string"), "enum": ["next", "current", "last", None]},
}
PLACE_ARG = {"type": _nullable("string"), "description": "The place name, only if the user said one."}
MARK_DONE_TOOL = _fn("mark_activity_done", "Mark an activity of the open trip as done (or not done).",
                     {"activity": ACTIVITY_ARG, "done": {"type": _nullable("boolean"), "description": "false to unmark."}, **TRIP_ARGS},
                     ["activity"])
SAVE_PLACE_TOOL = _fn("save_place", "Save the place on screen or the one just found to the user's saved places.",
                      {"place": PLACE_ARG})
UNSAVE_PLACE_TOOL = _fn("unsave_place", "Remove a place from the user's saved places.", {"place": PLACE_ARG})
ADD_EXPENSE_TOOL = _fn("add_expense", "Add money spent to the open trip's expenses (the user confirms first).", {
    "title": {"type": _nullable("string"), "description": "Short label, e.g. 'Auto', 'Lunch'."},
    "amount": {"type": "number", "description": "Rupees."},
    "category": {"type": _nullable("string"), "enum": ["food", "transport", "stay", "shopping", "tickets", "other", None]},
    **TRIP_ARGS,
}, ["amount"])
SWAP_TOOL = _fn("swap_activity", "Show alternatives to replace one activity of the open trip.",
                {"activity": ACTIVITY_ARG, "reason": {"type": _nullable("string")}, **TRIP_ARGS}, ["activity"])
REGEN_TOOL = _fn("regenerate_itinerary", "Rebuild a trip's whole itinerary (the user confirms first).", dict(TRIP_ARGS))
ACTION_TOOLS = [MARK_DONE_TOOL, SAVE_PLACE_TOOL, UNSAVE_PLACE_TOOL, ADD_EXPENSE_TOOL, SWAP_TOOL, REGEN_TOOL]



_DAY_ARG = {"type": _nullable("string"),
            "description": "today | tomorrow | day_after_tomorrow | YYYY-MM-DD | the day number as text, e.g. '2'. Kal = tomorrow, parso = day_after_tomorrow."}
WEATHER_REPLAN_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "weather_replan",
        "description": "Change the open trip's plan because of bad weather (swap outdoor stops for indoor ones). Asks the user "
                       "before anything changes. Not for weather questions (use get_weather).",
        "parameters": {"type": "object", "properties": {"day": _DAY_ARG}},
    },
}
OPTIMIZE_DAY_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "optimize_day",
        "description": "Reorder one day of the open trip (shorter travel, more relaxed, or more sights). Asks before changing.",
        "parameters": {
            "type": "object",
            "properties": {
                "day": _DAY_ARG,
                "goal": {"type": _nullable("string"), "enum": ["MINIMIZE_TRAVEL_TIME", "RELAXED", "MORE_SIGHTS", None]},
            },
        },
    },
}
OPTIMIZE_BUDGET_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "optimize_budget",
        "description": "Make the open trip's plan fit its budget with cheaper swaps. Asks before changing.",
        "parameters": {
            "type": "object",
            "properties": {"budget_inr": {"type": _nullable("number"),
                                          "description": "Total budget in rupees, only if the user said an amount."}},
        },
    },
}
SET_BUDGET_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "set_trip_budget",
        "description": "Set or change the OPEN trip's total budget amount. Asks before changing. Not for a new trip "
                       "being planned (use update_trip_draft) and not for fitting the plan to the budget (optimize_budget).",
        "parameters": {
            "type": "object",
            "properties": {"amount": {"type": "number", "description": "The new total budget in rupees, e.g. 40000."}},
            "required": ["amount"],
        },
    },
}
SMART_TOOLS = [WEATHER_REPLAN_TOOL, OPTIMIZE_DAY_TOOL, OPTIMIZE_BUDGET_TOOL, SET_BUDGET_TOOL]   # step 6 (+ budget)

TOOLS = [NAVIGATE_TOOL, ANSWER_TOOL, SEARCH_TOOL, NEARBY_TOOL, WEATHER_TOOL, TRAVEL_TIME_TOOL, LIST_TRIPS_TOOL, OPEN_TRIP_TOOL,
         CANT_HELP_TOOL,
         UPDATE_DRAFT_TOOL, CANCEL_DRAFT_TOOL] + ACTION_TOOLS + SMART_TOOLS
TOOL_NAMES = {t["function"]["name"] for t in TOOLS}


@dataclass
class TripInfo:
    title: str
    start_date: Optional[str]
    end_date: Optional[str]
    id: Optional[str] = None   # set by ws._resolve_trip only after the ownership check


@dataclass
class AgentResult:
    reply_text: str
    ui_actions: List[Dict[str, Any]] = field(default_factory=list)
    # navigate:<page> | map_focus | where | answer | weather | decline | unclear | list_trips | open_trip | reply | error
    action: str = "reply"
    llm_ms: int = 0                   # the deciding LLM call(s)
    tool_ms: int = 0                  # the tool (answer: cost guard + Gemini/OpenAI; look-ups: Google/DB/Open-Meteo)
    error_code: Optional[str] = None  # logs, the reply's error_code (app console / test panel), the debug store
    # Why it failed: sent as the reply's error_detail, saved in the debug store and logs/voice_errors.md.
    # Status codes and code / class names only: never the user's words, the transcript, tool arguments or the
    # provider's response body.
    error_detail: Optional[str] = None
    error_info: Dict[str, Any] = field(default_factory=dict)   # stage, attempt, attempts, model, status, tool, detail
    note: Optional[str] = None        # small on-screen text, never spoken (e.g. "Details badal sakti hain.")
    pending_actions: List[Dict[str, Any]] = field(default_factory=list)
    pending_confirmation: Optional[Dict[str, Any]] = None   # {id, summary}: the app shows the Confirm card
    step: Optional[str] = None                              # trip draft: ask | confirm_date | ready (logs)
    missing_count: Optional[int] = None                     # trip draft: missing fields (logs)
    google_calls: Optional[int] = None                      # Google requests made by a look-up tool (logs)
    note_attribution: Optional[str] = None                  # "Google Maps" when the note is Google Maps content


def template_language(stt_language: Optional[str], text: Optional[str] = None) -> str:
    """Template language from the user's words (item 8); Whisper's tag only when there are no words."""
    if text is not None:
        return detect_lang(text, stt_language)
    lang = (stt_language or "").strip().lower()
    return "en" if lang == "en" else "hi"


REPLY_LANGUAGE_LINE = "- Reply in the language the user spoke: Hinglish in Roman script, Hindi, or English."


def build_system_prompt(screen: Optional[str], trip: Optional[TripInfo], today: Optional[str] = None,
                        draft_line: str = "none", trip_context: str = "none", reply_rule: Optional[str] = None) -> str:
    """reply_rule: the chosen voice language's line (voice/languages.reply_rule) in place of REPLY_LANGUAGE_LINE;
    None (auto) = the prompt exactly as before."""
    trip_line = (f"{trip.title} ({trip.start_date or '?'} to {trip.end_date or '?'})" if trip else "none")
    if today is None:
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
        today = f"{now.strftime('%A %d %B %Y')} ({now.date().isoformat()})"
    prompt = SYSTEM_PROMPT.format(screen=(screen or "unknown")[:120], trip_line=trip_line, today=today,
                                  draft_line=draft_line, trip_context=trip_context)
    return prompt.replace(REPLY_LANGUAGE_LINE, reply_rule, 1) if reply_rule else prompt


def _draft_line(d) -> str:
    """The draft for the prompt: field names and values the user gave (in the prompt only, never logged)."""
    if d is None:
        return "none"
    have = {k: v for k, v in {
        "destination": (d.destination or {}).get("name"), "origin_city": (d.origin_city or {}).get("name"),
        "start_date": d.start_date, "end_date": d.end_date, "days": d.days, "adults": d.adults,
        "children": d.children, "budget_inr": d.budget_inr, "purpose": getattr(d, "purpose_type", None),
        "base_area": (getattr(d, "base_area", None) or {}).get("name")}.items() if v is not None}
    asked = f"; our last question asked for {d.last_asked}" if getattr(d, "last_asked", None) else ""
    return f"have {json.dumps(have)}; still missing {d.missing_fields()} (our code asks for them){asked}"


def trim_sentences(text: str, limit: int = 2) -> str:
    """Spoken replies stay short: keep the first `limit` sentences."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    parts = re.split(r"(?<=[.!?।])\s+", text)
    return " ".join(parts[:limit]).strip()


def is_garbled(text: str) -> bool:
    """No real words at all (noise, a single letter, only symbols): no LLM call needed.
    A number counts as content: "50000" is a real answer to "kitna budget hai?".
    Devanagari: one letter is a real word ("हाँ", "जी" are a consonant plus vowel signs, which are marks, not
    letters). Latin keeps the old rule: fewer than 2 letters ("a") is noise."""
    if re.search(r"\d", text or ""):
        return False
    if any(is_devanagari_letter(ch) for w in tu_words(text) for ch in w):
        return False
    letters = re.findall(r"[^\W\d_]", text or "", re.UNICODE)
    return len(letters) < 2


_YES = {"haan", "haa", "ha", "han", "haanji", "ji", "yes", "yeah", "yep", "sure", "ok", "okay", "theek", "thik", "hai",
        "dikhao", "dikha", "do", "show", "please", "zaroor", "bilkul", "kholo", "it", "me", "on", "map", "the", "par", "pe"}
_YES_CORE = {"haan", "haa", "ha", "han", "haanji", "yes", "yeah", "yep", "sure", "ok", "okay", "zaroor", "bilkul", "theek", "thik",
             "dikhao", "show"}
_NO = {"nahi", "nahin", "na", "no", "nope", "mat", "rehne", "rahne", "do", "dijiye", "ji", "thanks", "thank", "you", "zarurat"}
_NO_CORE = {"nahi", "nahin", "na", "no", "nope", "mat", "rehne", "rahne", "cancel"}
_NO.update({"cancel", "karo", "kar", "trip", "banao", "galat", "wrong"})
_YES.update({"sahi", "correct", "right", "confirm", "proceed", "kar", "banao", "haanji", "bilkul"})
_YES_CORE.update({"sahi", "correct", "right", "confirm", "proceed"})

# Devanagari (Whisper often writes Hindi answers in Devanagari: "हाँ।"). Stored in the canonical form words()
# produces (हाँ -> हां, ज़रूर -> जरूर, नही -> नहीं), so every spelling variant matches one entry.
# Same rule as the Roman sets: yes only if every word is a yes word and at least one is a core yes word.
_YES_HI_CORE = {"हां", "हा", "हांजी", "जी", "ठीक", "सही", "बिल्कुल", "ज़रूर", "जरूर", "ओके", "यस", "कन्फर्म", "दिखाओ"}
_YES_HI = _YES_HI_CORE | {"है", "कर", "दो", "करो", "दिखा", "दीजिए", "दीजिये"}
_NO_HI_CORE = {"नहीं", "नही", "ना", "मत", "रहने", "रुको", "कैंसल", "रद्द", "नो"}
_NO_HI = _NO_HI_CORE | {"दो", "करो", "कर", "गलत", "ग़लत", "दीजिए", "दीजिये", "जी"}
_YES.update(canon(w) for w in _YES_HI)
_YES_CORE.update(canon(w) for w in _YES_HI_CORE)
_NO.update(canon(w) for w in _NO_HI)
_NO_CORE.update(canon(w) for w in _NO_HI_CORE)
# First word that cancels a trip draft ("cancel karo", "रद्द करो", "कैंसल").
_CANCEL_FIRST_WORDS = {canon("कैंसल"), canon("रद्द")}


def yes_or_no(text: str) -> Optional[str]:
    words = tu_words(text)
    if not words or len(words) > 5:
        return None
    if set(words) <= _YES and set(words) & _YES_CORE:
        return "yes"
    if set(words) <= _NO and set(words) & _NO_CORE:
        return "no"
    return None


# The checked-plan offer asks "Isse shuru karein?", so people answer "haan, shuru karo" / "हाँ, शुरू करो".
# For THIS offer only, start words may come with the yes; a yes word is still required ("shuru karo" alone
# does not accept). yes_or_no() itself is unchanged for every other question.
_PLAN_START = {canon(w) for w in ("shuru", "suru", "start", "karo", "karein", "karen", "kare", "kariye", "kijiye",
                                  "kar", "do", "ji", "please", "isse", "ise", "yahi", "plan", "se",
                                  "शुरू", "करो", "करें", "करे", "करिए", "करिये", "कीजिए", "कीजिये", "कर",
                                  "इससे", "इसे", "यही", "प्लान", "से", "जी")}


def plan_offer_yes(text: str) -> bool:
    if yes_or_no(text) == "yes":
        return True
    words = tu_words(text)
    return bool(words) and len(words) <= 6 and set(words) <= (_YES | _PLAN_START) and bool(set(words) & _YES_CORE)


# "I don't know where from" -> go on without a starting city. Two kinds, decided by CODE:
#  "short": only skip words + fillers ("पता।", "pata nahi yaar", "मैंने बोला, पता नहीं कहाँ से जाऊँगा।") -> no model call.
#  "long":  a skip phrase plus other words ("pata nahi, Delhi se") -> the model runs; a real city it extracts wins,
#           otherwise the origin is skipped (and cleared if one was set).
# Only when our last question asked for the origin, or the sentence itself talks about the start (kahan se /
# starting / शुरू). A "when" word without a start word ("pata nahi kab jaana hai") is never a skip.
_ORIGIN_SKIP_PHRASES = [tuple(tu_words(p)) for p in (
    "pata nahi", "pata nahin", "pata nai", "nahi pata", "nahin pata", "nai pata", "maloom nahi", "malum nahi",
    "nahi maloom", "chhodo", "chodo", "chhod do", "chod do", "chhodiye", "chodiye", "skip", "abhi nahi", "abhi nahin",
    "baad mein", "don't know", "dont know", "do not know", "no idea", "not sure", "पता नहीं", "नहीं पता", "मालूम नहीं",
    "नहीं मालूम", "छोड़ो", "छोड़ दो", "छोड़िए", "छोड़िये", "अभी नहीं", "बाद में", "स्किप")]
_ORIGIN_PATA = {canon("pata"), canon("पता")}                 # "पता।" alone: speech-to-text cut "पता नहीं" short
_ORIGIN_KOI = {canon("koi"), canon("कोई")}                   # "koi starting city nahi hai"
_ORIGIN_NAHI = {canon("nahi"), canon("nahin"), canon("नहीं")}
_ORIGIN_START = {canon(w) for w in ("kahan", "kahaan", "kaha", "starting", "start", "shuru", "suru", "origin", "from",
                                    "कहां", "कहा", "शुरू", "शुरु", "स्टार्टिंग")}
_ORIGIN_WHEN = {canon(w) for w in ("kab", "when", "date", "tareekh", "tarikh", "कब", "तारीख")}
_ORIGIN_SKIP_FILLER = {canon(w) for w in (
    "mujhe", "muje", "abhi", "karo", "kar", "karein", "do", "dijiye", "ji", "i", "it", "please", "yaar", "toh", "to",
    "bhi", "hai", "ye", "yeh", "isko", "city", "sorry", "maine", "main", "mai", "bola", "boli", "kaha", "se", "jaunga",
    "jaaunga", "jaungi", "jaaungi", "jaana", "jaayenge", "jayenge", "hoga", "koi", "kuch", "nahi", "nahin", "where",
    "we", "will", "the", "a", "shahar", "jagah", "ka", "ki", "ke", "pata",
    "मुझे", "करो", "कर", "करें", "दो", "दीजिए", "जी", "है", "भी", "तो", "यह", "इसे", "मैंने", "मैं", "बोला", "बोली", "कहा",
    "से", "जाऊंगा", "जाऊंगी", "जाना", "जाएंगे", "जायेंगे", "होगा", "कोई", "कुछ", "नहीं", "शहर", "जगह", "का", "की", "के",
    "यार", "पता")} | _ORIGIN_START


def origin_skip_kind(text: str, origin_asked: bool) -> Optional[str]:
    """None / "short" / "long" (see above)."""
    words = tu_words(text)
    if not words:
        return None
    ws = set(words)
    start = bool(ws & _ORIGIN_START)
    if not (origin_asked or start) or (ws & _ORIGIN_WHEN and not start):
        return None
    found = set()
    for phrase in _ORIGIN_SKIP_PHRASES:
        n = len(phrase)
        for i in range(len(words) - n + 1):
            if tuple(words[i:i + n]) == phrase:
                found.update(range(i, i + n))
    only_fillers = all(i in found or w in _ORIGIN_SKIP_FILLER for i, w in enumerate(words))
    pata_alone = bool(ws & _ORIGIN_PATA) and only_fillers and len(words) <= 3
    koi_nahi = bool(ws & _ORIGIN_KOI) and bool(ws & _ORIGIN_NAHI) and start
    if not (found or pata_alone or koi_nahi):
        return None
    return "short" if only_fillers and len(words) <= 10 else "long"


def is_origin_skip(text: str) -> bool:
    """A whole answer to "Kahan se jaana hai?" that only says "don't know" (handled without the model)."""
    return origin_skip_kind(text, True) == "short"


# ---------------- memory (Redis)

def _mem_key(user_id: str, conversation_id: str) -> str:
    return f"voice:mem:{user_id}:{conversation_id}"


def load_memory(redis_conn, user_id: str, conversation_id: str) -> List[Dict[str, str]]:
    try:
        raw = redis_conn.get(_mem_key(user_id, conversation_id))
        if not raw:
            return []
        data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        return [m for m in data if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
    except Exception as err:
        # The turn continues without memory; say why instead of silently dropping context.
        logger.warning("[VOICE AGENT] memory load failed: %s: %s", type(err).__name__, str(err)[:200])
        return []


def save_turn(redis_conn, user_id: str, conversation_id: str, user_text: str, reply_text: str) -> None:
    try:
        history = load_memory(redis_conn, user_id, conversation_id)
        history += [{"role": "user", "content": user_text}, {"role": "assistant", "content": reply_text}]
        history = history[-MEMORY_TURNS * 2:]
        redis_conn.setex(_mem_key(user_id, conversation_id), MEMORY_TTL_SECONDS, json.dumps(history))
    except Exception as err:
        logger.warning("[VOICE AGENT] memory save failed: %s: %s", type(err).__name__, str(err)[:200])


def clear_memory(redis_conn, user_id: str, conversation_id: Optional[str] = None) -> None:
    """end_session: the conversation's memory (or all of the user's voice memory) is deleted."""
    try:
        if conversation_id:
            redis_conn.delete(_mem_key(user_id, conversation_id))
            redis_conn.delete(_pending_key(user_id, conversation_id))
            redis_conn.delete(f"voice:draft:{user_id}:{conversation_id}")    # step 4: the trip draft
            redis_conn.delete(f"voice:confirm:{user_id}:{conversation_id}")  # step 4: the pending confirmation
            redis_conn.delete(f"voice:lastplace:{user_id}:{conversation_id}")  # step 5: the last place found
        else:
            for prefix in ("voice:mem", "voice:pending", "voice:draft", "voice:confirm", "voice:lastplace"):
                for key in redis_conn.scan_iter(f"{prefix}:{user_id}:*"):
                    redis_conn.delete(key)
    except Exception as err:
        logger.warning("[VOICE AGENT] memory clear failed: %s: %s", type(err).__name__, str(err)[:200])


def _pending_key(user_id: str, conversation_id: str) -> str:
    return f"voice:pending:{user_id}:{conversation_id}"


def save_pending(redis_conn, user_id: str, conversation_id: str, actions: List[Dict[str, Any]]) -> None:
    try:
        redis_conn.setex(_pending_key(user_id, conversation_id), PENDING_TTL_SECONDS, json.dumps(actions))
    except Exception as err:
        logger.warning("[VOICE AGENT] pending save failed: %s: %s", type(err).__name__, str(err)[:200])


def pop_pending(redis_conn, user_id: str, conversation_id: str) -> List[Dict[str, Any]]:
    try:
        key = _pending_key(user_id, conversation_id)
        raw = redis_conn.get(key)
        if raw:
            redis_conn.delete(key)
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            return [a for a in data if isinstance(a, dict) and a.get("type") in ("map_focus", "navigate")]
    except Exception as err:
        logger.warning("[VOICE AGENT] pending pop failed: %s: %s", type(err).__name__, str(err)[:200])
    return []


# ---------------- the turn

def _navigate(args: Dict[str, Any], lang: str, has_trip: bool) -> AgentResult:
    page = args.get("page")
    day = args.get("day")
    route, err = pages.resolve(page, day, has_trip)
    if err is None:
        return AgentResult(pages.confirm_text(page, day, lang),
                           ui_actions=[{"type": "navigate", "to": route}], action=f"navigate:{page}")
    if err == "no_trip":
        return AgentResult(pages.NO_TRIP_REPLY[lang], ui_actions=[{"type": "navigate", "to": pages.ROUTES["my_trips"]}],
                           action="navigate:my_trips", error_code="no_trip")
    return AgentResult(pages.WHICH_PAGE_REPLY[lang], action="reply", error_code=err)


def _from_tool(r) -> AgentResult:
    return AgentResult(r.reply_text, ui_actions=list(r.ui_actions), action=r.action, error_code=r.error_code,
                       pending_actions=list(getattr(r, "pending_actions", []) or []),
                       google_calls=getattr(r, "google_calls", None), note=getattr(r, "note", None),
                       note_attribution=getattr(r, "note_attribution", None))


def _norm_text(s: str) -> str:
    """Lowercase words joined by spaces, any script (voice/text_utils.normalize_text)."""
    return tu_normalize(s)


def _starts_cancel(transcript: str) -> bool:
    words = tu_words(transcript)
    return bool(words) and (words[0].startswith("cancel") or words[0] in _CANCEL_FIRST_WORDS)


# ---------------- create a trip by voice (step 4)

READY_REPLY = {"hi": "Sab details review page par hain. Check karke Proceed dabaiye, ya haan boliye.",
               "en": "All details are on the review page. Check them and tap Proceed, or say yes."}
CONFIRMED_REPLY = {"hi": "Trip bana raha hoon.", "en": "Creating your trip."}
NOTHING_TO_CONFIRM = {"hi": "Abhi confirm karne ke liye kuch nahi hai.", "en": "There's nothing to confirm right now."}
CANCELLED_REPLY = {"hi": "Theek hai, trip nahi banayi. Kuch save nahi hua.", "en": "Okay, no trip was created. Nothing was saved."}
REPLACED_NOTE = {"hi": "Pichli trip ka draft hata diya.", "en": "I dropped the previous trip draft."}
DATE_AGAIN = {"hi": "Theek hai, kab se kab tak jaana hai?", "en": "Okay, from which date to which date?"}
# Checked plans (pilgrimage cards): code decides when to offer; these are the fixed words.
PLAN_OFFER = {"hi": "{name} ka ek checked plan hai. Isse shuru karein?",
              "en": "There's a checked plan for {name}. Shall we start with it?"}
PLAN_ACCEPTED = {"hi": "Theek hai, checked plan se banate hain.", "en": "Okay, we'll start from the checked plan."}
PLAN_DECLINED = {"hi": "Theek hai.", "en": "Okay."}


def _draft_today():
    from trip_lifecycle import today_ist
    return today_ist()


def _log_origin(d, conversation_id: str, event: str, **flags: bool) -> None:
    """Counts and flags only, never the city."""
    extra = "".join(f" {k}=true" for k, v in flags.items() if v)
    print(f"[TRIP DRAFT] event={event} origin_set={'true' if d.origin_city else 'false'} origin_asked={d.origin_asked} "
          f"origin_failed={d.origin_failed} origin_skipped={'true' if d.origin_skipped else 'false'} "
          f"same_as_dest_ok={'true' if d.origin_same_ok else 'false'}{extra} source=voice draft={conversation_id}", flush=True)


def _log_purpose(d, conversation_id: str, event: str, **flags: bool) -> None:
    """The type, counts and flags only, never the user's words or the area's name."""
    extra = "".join(f" {k}=true" for k, v in flags.items() if v)
    print(f"[TRIP DRAFT] event=purpose_{event} purpose={d.purpose_type or 'none'} purpose_asked={d.purpose_asked} "
          f"purpose_skipped={'true' if d.purpose_skipped else 'false'} area_set={'true' if d.base_area else 'false'} "
          f"area_asked={d.area_asked} area_failed={d.area_failed} area_skipped={'true' if d.area_skipped else 'false'}"
          f"{extra} source=voice draft={conversation_id}", flush=True)


_PURPOSE_SKIP_MAX_WORDS = 6


def is_purpose_area_skip(text: str) -> bool:
    """A short "pata nahi" / "kuch nahi" / "skip" answer to the purpose or area question (no model call)."""
    from trip_purpose import is_purpose_skip
    return 0 < len(tu_words(text)) <= _PURPOSE_SKIP_MAX_WORDS and is_purpose_skip(text)


def skip_purpose_area(redis_conn, user_id: str, conversation_id: str, d, lang: str) -> AgentResult:
    """"pata nahi" to "Kis kaam se ja rahe hain?" (no area question then) or to "Kis area mein ...?": go on without it."""
    from voice import draft as D
    if d.purpose_pending:
        d.purpose_skipped = d.purpose_type is None or d.purpose_skipped
    if d.area_pending:
        d.area_skipped = True
    d.purpose_pending = d.area_pending = False
    _log_purpose(d, conversation_id, "skipped")
    return draft_next(redis_conn, user_id, conversation_id, d, lang, D.PURPOSE_SKIPPED[lang])


def draft_next(redis_conn, user_id: str, conversation_id: str, d, lang: str, prefix: str = "") -> AgentResult:
    """What to say next for a draft. CODE decides: origin = destination? / ask (<= 2 things) / read back / ready."""
    from voice import draft as D, pending as P
    if d.origin_candidate:
        d.awaiting, d.last_asked = "origin_check", ["origin_city"]
        D.save(redis_conn, user_id, conversation_id, d)
        name = d.origin_candidate.get("name", "")
        return AgentResult(f"{prefix} {D.ORIGIN_CHECK[lang].format(name=name)}".strip(), action="trip_draft",
                           step="confirm_origin", missing_count=len(d.missing_fields()))
    if d.origin_is_destination():
        d.awaiting, d.last_asked = "origin_same", ["origin_city"]
        D.save(redis_conn, user_id, conversation_id, d)
        name = (d.origin_city or {}).get("name", "")
        return AgentResult(f"{prefix} {D.ORIGIN_SAME[lang].format(name=name)}".strip(), action="trip_draft",
                           step="confirm_origin", missing_count=len(d.missing_fields()))
    step = d.next_step()
    missing = d.missing_fields()
    if step == "ask":
        d.awaiting = None
        d.last_asked = D.ask_fields(missing, ask_origin=d.wants_origin(), ask_purpose=d.wants_purpose(),
                                    ask_area=d.wants_area())
        if "origin_city" in d.last_asked:
            d.origin_asked += 1
            d.origin_pending = True
        if "purpose" in d.last_asked:
            d.purpose_asked += 1
            d.purpose_pending = True
        if "base_area" in d.last_asked:
            d.area_asked += 1
            d.area_pending = True
        D.save(redis_conn, user_id, conversation_id, d)
        if {"purpose", "base_area"} & set(d.last_asked):
            _log_purpose(d, conversation_id, "ask")
        text = f"{prefix} {D.question_for(missing, lang, days_known=bool(d.days), ask_origin='origin_city' in d.last_asked, ask_purpose='purpose' in d.last_asked, ask_area='base_area' in d.last_asked)}".strip()
        return AgentResult(text, action="trip_draft", step="ask", missing_count=len(missing))
    if step == "confirm_date":
        d.awaiting, d.last_asked = "date", []
        D.save(redis_conn, user_id, conversation_id, d)
        return AgentResult(f"{prefix} {D.readback(d, lang)}".strip(), action="trip_draft", step="confirm_date", missing_count=0)
    # ready: open the review page with the draft; one pending confirmation (replaces any older one)
    d.awaiting, d.last_asked = None, []
    D.save(redis_conn, user_id, conversation_id, d)
    _log_origin(d, conversation_id, "ready")
    pc = P.save(redis_conn, user_id, conversation_id, "create_trip", D.summary(d, lang))
    return AgentResult(f"{prefix} {READY_REPLY[lang]}".strip(),
                       ui_actions=[{"type": "open_review", "prefill": D.prefill(d)}],
                       action="trip_draft", step="ready", missing_count=0,
                       pending_confirmation={"id": pc["id"], "summary": pc["summary"]})


def update_draft(redis_conn, user_id: str, conversation_id: str, args: Dict[str, Any], lang: str) -> AgentResult:
    from voice import draft as D, pending as P
    d = D.load(redis_conn, user_id, conversation_id)
    prefix = ""
    if d is not None and args.get("start_new") is True:
        d = None
        prefix = REPLACED_NOTE[lang]
    had_pending = P.get(redis_conn, user_id, conversation_id) is not None
    if had_pending:
        P.clear(redis_conn, user_id, conversation_id)   # details changed: the summary must be confirmed again
    d = d or D.TripDraftState()
    prev_dest_id = (d.destination or {}).get("id")
    origin_was_asked, d.origin_pending = d.origin_pending, False
    purpose_was_asked, d.purpose_pending = d.purpose_pending, False
    area_was_asked, d.area_pending = d.area_pending, False
    skip_hint, d.skip_hint = d.skip_hint, False
    was_skipped = d.origin_skipped
    res = D.apply_update(d, {k: v for k, v in args.items() if k != "start_new"}, lang, _draft_today())
    origin_note, origin_retry, cleared = "", "", False
    if res.date_rolled_forward or res.date_fields_missing:   # flags only, never the words or the date
        print(f"[TRIP DRAFT] event=dates date_rolled_forward={'true' if res.date_rolled_forward else 'false'} "
              f"date_fields_missing={'true' if res.date_fields_missing else 'false'} source=voice draft={conversation_id}", flush=True)
    if skip_hint and not res.origin_not_found and not res.origin_unsure and "origin_city" not in res.changed:
        # "pata nahi kahan se ..." and the model found no (new) city: no origin, never asked again
        cleared = d.origin_city is not None
        if cleared:
            d.dates_confirmed = False                 # read back again without it
        d.origin_city, d.origin_candidate, d.origin_skipped = None, None, True
        origin_note = ORIGIN_SKIPPED[lang]
    elif res.origin_not_found:
        d.origin_failed += 1
        if d.origin_failed >= 2 or d.origin_asked >= D.MAX_ORIGIN_ASKS or was_skipped:
            d.origin_skipped = True   # second miss: go on without it, never a third question
            origin_note = D.ORIGIN_GIVE_UP[lang].format(name=res.origin_not_found)
        else:
            d.origin_asked += 1       # one retry: speech-to-text often gets Indian town names wrong
            d.origin_pending, d.last_asked = True, ["origin_city"]
            origin_retry = D.ORIGIN_RETRY[lang].format(name=res.origin_not_found)
    elif origin_was_asked and "origin_city" not in res.changed:
        d.origin_skipped = True       # asked, not given (or not a place name): never asked again
    if res.origin_not_found or res.origin_invalid or res.origin_unsure or "origin_city" in res.changed or origin_was_asked \
            or skip_hint:
        _log_origin(d, conversation_id, "update", origin_discarded_stopword=res.origin_stopword,
                    origin_cleared_by_skip=cleared, origin_name_mismatch=res.origin_unsure)
    # The purpose and base area: like the origin. Asked and not given -> never asked again; an area not found near the
    # destination -> one retry, then go on without it.
    area_retry, area_note = "", ""
    if purpose_was_asked and "purpose" not in res.changed and d.purpose_type is None:
        d.purpose_skipped = True
    if res.area_not_found:
        d.area_failed += 1
        city = str((d.destination or {}).get("city") or (d.destination or {}).get("name") or "").split(",")[0]
        if d.area_failed >= 2 or d.area_asked >= D.MAX_AREA_ASKS:
            d.area_skipped = True
            area_note = D.AREA_GIVE_UP[lang].format(name=res.area_not_found)
        else:
            d.area_asked += 1
            d.area_pending, d.last_asked = True, ["base_area"]
            area_retry = D.AREA_RETRY[lang].format(name=res.area_not_found, city=city)
    elif area_was_asked and "base_area" not in res.changed:
        d.area_skipped = True
    if purpose_was_asked or area_was_asked or "purpose" in res.changed or "base_area" in res.changed \
            or res.area_not_found or res.purpose_skip:
        _log_purpose(d, conversation_id, "update", area_not_found=bool(res.area_not_found), area_invalid=res.area_invalid)
    if res.problems:
        D.save(redis_conn, user_id, conversation_id, res.draft)
        retries = [x for x in (origin_retry, area_retry) if x]
        r = AgentResult(" ".join(res.problems[:2] + retries), action="trip_draft",
                        step="ask", missing_count=len(res.draft.missing_fields()), error_code="refused_value")
        return r
    if origin_retry:
        D.save(redis_conn, user_id, conversation_id, res.draft)
        return AgentResult(origin_retry, action="trip_draft", step="ask_origin", missing_count=len(res.draft.missing_fields()))
    if area_retry:
        D.save(redis_conn, user_id, conversation_id, res.draft)
        return AgentResult(area_retry, action="trip_draft", step="ask_area", missing_count=len(res.draft.missing_fields()))
    if "destination" in res.changed and (res.draft.destination or {}).get("id") != prev_dest_id:
        offer = _plan_offer(res.draft, args.get("destination"))
        if offer is not None:
            D.save(redis_conn, user_id, conversation_id, res.draft)
            return AgentResult(f"{prefix} {PLAN_OFFER[lang].format(name=offer.short_name)}".strip(),
                               action="trip_draft", step="plan_offer", missing_count=len(res.draft.missing_fields()))
    dd = res.draft
    origin_readback_next = (dd.origin_city is not None and not dd.origin_candidate and not dd.origin_is_destination()
                            and dd.next_step() == "confirm_date")
    dest_new = "destination" in res.changed and (res.draft.destination or {}).get("id") != prev_dest_id
    if dest_new and not prefix and not origin_readback_next:
        # Said only on the turn the destination is first set or changed (the model re-sends it on every update).
        # (not before "<origin> se <destination>, ...": that already names the destination)
        name = (res.draft.destination or {}).get("name", "")
        length = f", {res.draft.days} din" if res.draft.days and lang != "en" else (f", {res.draft.days} days" if res.draft.days else "")
        prefix = f"{name}{length}."
    prefix = f"{prefix} {origin_note} {area_note}".strip()
    return draft_next(redis_conn, user_id, conversation_id, res.draft, lang, prefix)


ORIGIN_SKIPPED = {"hi": "Theek hai, starting city ke bina.", "en": "Okay, without a starting city."}


def skip_origin(redis_conn, user_id: str, conversation_id: str, d, lang: str) -> AgentResult:
    """'pata nahi' (to 'Kahan se jaana hai?', or 'pata nahi kahan se' any time): go on without a starting city.
    An origin already set is cleared. Never asked again in this draft (a city the user says later is still taken)."""
    from voice import pending as P
    cleared = d.origin_city is not None or d.origin_candidate is not None
    if d.origin_city is not None:
        d.dates_confirmed = False                     # the read-back named that origin: read back again
        P.clear(redis_conn, user_id, conversation_id)  # and a Confirm card made with it must not be confirmed
    d.origin_city, d.origin_candidate = None, None
    d.origin_pending, d.origin_skipped, d.skip_hint = False, True, False
    if d.purpose_pending or d.area_pending:    # one "pata nahi" to a question that asked both
        d.purpose_skipped = d.purpose_skipped or (d.purpose_pending and d.purpose_type is None)
        d.area_skipped = d.area_skipped or d.area_pending
        d.purpose_pending = d.area_pending = False
    if d.awaiting in ("origin_check", "origin_same"):
        d.awaiting = None
    _log_origin(d, conversation_id, "skipped", origin_cleared_by_skip=cleared)
    return draft_next(redis_conn, user_id, conversation_id, d, lang, ORIGIN_SKIPPED[lang])


def answer_origin_same(redis_conn, user_id: str, conversation_id: str, d, said: Optional[str], lang: str) -> Optional[AgentResult]:
    """The answer to "Kolkata se Kolkata hi jaana hai? Sahi hai?" (asked once). Yes keeps it; no drops it.
    Anything else drops it too and returns None, so the turn goes on as usual ("nahi, Patna se" sets a new one)."""
    from voice import draft as D
    kind, d.awaiting = d.awaiting, None
    if kind == "origin_check":
        # "Patna se? Sahi hai?" (asked once). Yes -> the origin; no -> none, not asked again; anything else -> none,
        # and the turn goes on ("nahi, Kolkata se" sets Kolkata).
        candidate, d.origin_candidate = d.origin_candidate, None
        if said == "yes" and candidate:
            d.origin_city, d.origin_skipped, d.dates_confirmed, d.origin_same_ok = candidate, False, False, False
            _log_origin(d, conversation_id, "name_check_yes")
            return draft_next(redis_conn, user_id, conversation_id, d, lang)
        d.origin_skipped, d.origin_pending = True, False
        _log_origin(d, conversation_id, "name_check_no")
        if said == "no":
            return draft_next(redis_conn, user_id, conversation_id, d, lang, PLAN_DECLINED[lang])
        D.save(redis_conn, user_id, conversation_id, d)
        return None
    if said == "yes":
        d.origin_same_ok = True
        _log_origin(d, conversation_id, "same_as_dest_yes")
        return draft_next(redis_conn, user_id, conversation_id, d, lang, PLAN_DECLINED[lang])
    d.origin_city, d.origin_skipped, d.origin_pending = None, True, False
    _log_origin(d, conversation_id, "same_as_dest_no")
    if said == "no":
        return draft_next(redis_conn, user_id, conversation_id, d, lang, PLAN_DECLINED[lang])
    D.save(redis_conn, user_id, conversation_id, d)
    return None


def _plan_offer(d, said: Any):
    """A new destination: forget any earlier offer, then offer a checked plan once if what the user SAID
    matches a card (plain code, pilgrimage.match_card). Returns the card to offer, or None (old flow)."""
    import pilgrimage
    d.plan_offer = d.plan_offer_card = d.plan_card_id = None
    card = pilgrimage.match_card(str(said or ""))
    if card is None:
        return None
    d.plan_offer, d.plan_offer_card, d.awaiting = "asked", card.id, "card"
    return card


def answer_plan_offer(redis_conn, user_id: str, conversation_id: str, d, said: Optional[str], lang: str) -> Optional[AgentResult]:
    """The answer to \"... ka ek checked plan hai. Isse shuru karein?\". Only a yes accepts. \"nahi\" declines and
    continues; anything else declines and returns None so the turn is handled as usual."""
    import pilgrimage
    from voice import draft as D
    from datetime import timedelta
    d.awaiting = None
    card = pilgrimage.get_card(d.plan_offer_card) if said == "yes" else None
    if card is None:
        d.plan_offer, d.plan_card_id = "declined", None
        D.save(redis_conn, user_id, conversation_id, d)
        if said == "no":
            return draft_next(redis_conn, user_id, conversation_id, d, lang, PLAN_DECLINED[lang])
        return None
    d.plan_offer, d.plan_card_id = "accepted", card.id
    print(f"[PILGRIMAGE] accepted card={card.id} draft={conversation_id}", flush=True)
    if not d.days and not d.end_date:
        start = D.parse_date(d.start_date) if d.start_date else None
        if start:   # dates already given without a length: the card's default length
            d.end_date = (start + timedelta(days=card.default_days - 1)).isoformat()
            d.dates_confirmed = False
        else:
            d.days = card.default_days
    return draft_next(redis_conn, user_id, conversation_id, d, lang, PLAN_ACCEPTED[lang])


# A pending item was found and used ("smart_failed": it ran and the service failed; nothing changed).
CONFIRMED_ACTIONS = {"trip_confirm", "expense_added", "regen_queued", "smart_applied", "smart_failed"}
NOTHING_CHANGED = {"hi": "Theek hai, kuch nahi badla.", "en": "Okay, nothing changed."}
DELETE_REPLY = {"hi": "Trip delete karne ke liye button khud dabaiye, dhyan se.",
                "en": "To delete a trip, please tap the delete button yourself, carefully."}


def confirm_pending(redis_conn, user_id: str, conversation_id: str, lang: str, pending_id: Optional[str] = None,
                    open_trip_id: Optional[str] = None) -> AgentResult:
    """
    The ONE confirm action for every pending confirmation (voice "haan" and the Confirm button alike).
    Takes it once: a second confirm finds nothing and runs nothing. A pending big action carries its trip_id;
    it runs only if that trip is still the user's (trip_actions) and still the one meant (open_trip_id, see
    actions.same_trip).
    """
    from voice import pending as P
    from voice.tools import actions as A
    current = P.get(redis_conn, user_id, conversation_id)
    if current and current.get("tool") == "create_trip":
        return confirm_trip(redis_conn, user_id, conversation_id, lang, pending_id)
    pc = P.take(redis_conn, user_id, conversation_id, pending_id)
    if not pc:
        return AgentResult(NOTHING_TO_CONFIRM[lang], action="confirm_none", error_code="no_pending")
    from voice.tools import smart
    if pc.get("tool") in smart.SMART_TOOL_NAMES:   # step 6: weather replan / optimize day / optimize budget
        return smart.apply_confirmed(pc, user_id, lang, redis_conn)
    if pc.get("tool") == "add_expense":
        return A.run_add_expense(user_id, pc.get("data") or {}, lang, open_trip_id)
    if pc.get("tool") == "regenerate_itinerary":
        return A.run_regenerate(redis_conn, user_id, pc.get("data") or {}, lang, open_trip_id)
    return AgentResult(NOTHING_TO_CONFIRM[lang], action="confirm_none", error_code="unknown_pending")


def cancel_pending(redis_conn, user_id: str, conversation_id: str, lang: str) -> AgentResult:
    """Cancel (button or "nahi"): nothing runs. For a trip being created, the draft goes too."""
    from voice import pending as P
    from voice.tools import smart
    current = P.get(redis_conn, user_id, conversation_id)
    if current is None or current.get("tool") == "create_trip":
        return cancel_trip(redis_conn, user_id, conversation_id, lang)
    P.clear(redis_conn, user_id, conversation_id)
    if current.get("tool") in smart.SMART_TOOL_NAMES:
        return AgentResult(NOTHING_CHANGED[lang], action="smart_cancel", step="cancelled")
    return AgentResult(NOTHING_CHANGED[lang], action="pending_cancel")


_DELETE_WORDS = re.compile(r"\b(delete|del|remove|hatao|hata|hatado|mitao|mita|mitado|uda|udao|erase)\b")
_TRIP_WORDS = re.compile(r"\b(trip|trips|yatra|safar|plan|itinerary)\b")


def is_delete_request(text: str) -> bool:
    """'meri trip delete karo': answered by code, never by a tool. (Removing a SAVED place is unsave_place.)"""
    t = (text or "").lower()
    return bool(_DELETE_WORDS.search(t) and _TRIP_WORDS.search(t) and "save" not in t)


def delete_refused(lang: str) -> AgentResult:
    return AgentResult(DELETE_REPLY[lang], ui_actions=[{"type": "navigate", "to": pages.ROUTES["trip"]}],
                       action="delete_refused")


def confirm_trip(redis_conn, user_id: str, conversation_id: str, lang: str, pending_id: Optional[str] = None) -> AgentResult:
    """
    The ONE confirm action, for voice "haan" and the Confirm button alike. Takes the pending confirmation once
    (a second confirm finds nothing) and tells the app to press Proceed on the review page: the wizard then
    saves the page's values through its own path (trips:create -> create_trip_for_user). Voice never creates
    a trip from its own copy of the draft.
    """
    from voice import draft as D, pending as P
    pc = P.take(redis_conn, user_id, conversation_id, pending_id)
    if not pc or pc.get("tool") != "create_trip":
        return AgentResult(NOTHING_TO_CONFIRM[lang], action="trip_confirm_none", error_code="no_pending")
    D.delete(redis_conn, user_id, conversation_id)
    # BR-1006: the trip is done, so this conversation's old turns (the dictation, the read-back) must not let the
    # model rebuild a draft from a later bare "haan". Only this conversation; the confirm turn itself isn't saved.
    clear_memory(redis_conn, user_id, conversation_id)
    return AgentResult(CONFIRMED_REPLY[lang], ui_actions=[{"type": "submit_review"}], action="trip_confirm", step="confirmed")


def cancel_trip(redis_conn, user_id: str, conversation_id: str, lang: str) -> AgentResult:
    from voice import draft as D, pending as P
    P.clear(redis_conn, user_id, conversation_id)
    D.delete(redis_conn, user_id, conversation_id)
    return AgentResult(CANCELLED_REPLY[lang], action="trip_cancel", step="cancelled")


LLM_ATTEMPTS = 2   # the first call plus one retry on an LLMTransient
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _join_detail(info: Dict[str, Any]) -> str:
    """The one-line detail saved in the debug store: the short detail plus model, attempt and tool."""
    parts = [info.get("detail") or ""]
    if info.get("model"):
        parts.append(f"model={info['model']}")
    if info.get("attempt"):
        parts.append(f"attempt {info['attempt']} of {info.get('attempts') or LLM_ATTEMPTS}")
    if info.get("tool"):
        parts.append(f"tool={info['tool']}")
    return ", ".join(p for p in parts if p)


def llm_error_info(err: Exception, attempt: int) -> Dict[str, Any]:
    """HTTP status, the provider's error code name, Retry-After, model and attempt. Never the message or body."""
    status = getattr(err, "status", None)
    code = getattr(err, "code", None)
    retry_after = getattr(err, "retry_after", None)
    bits = [f"HTTP {status}" if status else "no HTTP status"]
    if code:
        bits.append(f"code={code}")
    if retry_after:
        bits.append(f"retry_after={retry_after}s")
    return {"stage": "agent", "attempt": attempt, "attempts": LLM_ATTEMPTS, "status": status,
            "model": getattr(err, "model", None), "detail": ", ".join(bits)}


def crash_error_info(err: BaseException, tool: Optional[str] = None, stage: str = "agent") -> Dict[str, Any]:
    """Exception class and the file:line of the frame that raised it. Never str(err): it can hold user data."""
    where = "?"
    frames = traceback.extract_tb(err.__traceback__) if err.__traceback__ else []
    if frames:
        last = frames[-1]
        try:
            path = os.path.relpath(last.filename, _BACKEND_DIR)
        except ValueError:  # another drive on Windows
            path = os.path.basename(last.filename)
        where = f"{path.replace(os.sep, '/')}:{last.lineno} in {last.name}"
    return {"stage": "tool" if tool else stage, "tool": tool, "status": None,
            "detail": f"{type(err).__name__} at {where}"}


def _failed(code: str, info: Dict[str, Any], reply: Optional[str] = None) -> AgentResult:
    return AgentResult(reply or FALLBACK_REPLY, action="error", error_code=code, error_detail=_join_detail(info),
                       error_info=info)


def _decide(tool_calls: List[Dict[str, Any]], content: Optional[str], lang: str, has_trip: bool,
            user_id: Optional[str] = None, trip: Optional[TripInfo] = None,
            conversation_id: Optional[str] = None, redis_conn=None, trip_ctx=None,
            screen_place: Optional[Dict[str, Any]] = None,
            location: Optional[Tuple[float, float]] = None) -> AgentResult:
    """Check the model's choice and run the tool. user_id comes from the session, never from the model;
    location from the app (the user's own position, this turn only), never from the model."""
    call = next((c for c in tool_calls if c.get("name") in TOOL_NAMES), None)
    if call is None:
        if tool_calls:  # a tool we don't offer
            names = ",".join(str(tc.get("name")) for tc in tool_calls)[:100]
            return AgentResult(pages.WHICH_PAGE_REPLY[lang], action="reply", error_code="unknown_tool",
                               error_detail=f"model called a tool we don't offer: {names}")
        text = trim_sentences(content or "")
        # The model sometimes says the fixed lines as text instead of calling cant_help.
        if _norm_text(text) in {_norm_text(v) for v in DECLINE_REPLY.values()} or "sirf aapki trip" in text.lower():
            return AgentResult(DECLINE_REPLY[lang], action="decline")
        if _norm_text(text) in {_norm_text(v) for v in UNCLEAR_REPLY.values()}:
            return AgentResult(UNCLEAR_REPLY[lang], action="unclear")
        if "button khud dabaiye" in text.lower() or "delete" in text.lower():
            return delete_refused(lang)   # the model refused a delete in words: same fixed reply + open the trip
        return AgentResult(text or pages.WHICH_PAGE_REPLY[lang], action="reply")

    name, args = call["name"], call.get("arguments") or {}
    if not isinstance(args, dict):
        return _failed("bad_tool_args", {"stage": "tool", "tool": name,
                                         "detail": f"arguments were {type(args).__name__}, not an object"})
    if name == "navigate":
        return _navigate(args, lang, has_trip)
    if name == "cant_help":
        if args.get("reason") == "unclear":
            return AgentResult(UNCLEAR_REPLY[lang], action="unclear")
        return AgentResult(DECLINE_REPLY[lang], action="decline")

    if name in ("update_trip_draft", "cancel_trip_draft"):
        if not user_id or not conversation_id or redis_conn is None:
            missing = [n for n, gone in (("user_id", not user_id), ("conversation_id", not conversation_id),
                                         ("redis", redis_conn is None)) if gone]
            return _failed("no_user", {"stage": "tool", "tool": name, "detail": f"missing {'/'.join(missing)}"})
        if name == "cancel_trip_draft":
            return cancel_trip(redis_conn, user_id, conversation_id, lang)
        return update_draft(redis_conn, user_id, conversation_id, args, lang)

    if name in {t["function"]["name"] for t in ACTION_TOOLS}:
        if not user_id or not conversation_id or redis_conn is None:
            return AgentResult(FALLBACK_REPLY, action="error", error_code="no_user")
        from voice.tools import actions as A
        if name == "mark_activity_done":
            return A.mark_activity_done(user_id, trip_ctx, args, lang)
        if name == "save_place":
            return A.save_place(redis_conn, user_id, conversation_id, screen_place, args, lang)
        if name == "unsave_place":
            return A.unsave_place(redis_conn, user_id, conversation_id, screen_place, args, lang)
        if name == "add_expense":
            return A.add_expense(redis_conn, user_id, conversation_id, trip_ctx, args, lang)
        if name == "swap_activity":
            return A.swap_activity(user_id, trip_ctx, args, lang)
        return A.regenerate_itinerary(redis_conn, user_id, conversation_id, trip_ctx, args, lang)
    from voice.tools import smart
    if name in smart.SMART_TOOL_NAMES:
        if not user_id or not conversation_id or redis_conn is None:
            return _failed("no_user", {"stage": "tool", "tool": name, "detail": "missing user_id/conversation_id/redis"})
        if name == "set_trip_budget" and (trip is None or not trip.id):
            from voice import draft as D
            if D.load(redis_conn, user_id, conversation_id) is not None:
                # No trip open and a new trip is being planned: the amount belongs to that draft.
                return update_draft(redis_conn, user_id, conversation_id, {"budget_inr": args.get("amount")}, lang)
        if trip is None or not trip.id:
            return AgentResult(smart.TEXT["no_trip"][lang], ui_actions=[{"type": "navigate", "to": pages.ROUTES["my_trips"]}],
                               action="smart_no_trip", error_code="no_trip")
        return smart.propose(name, args, user_id, trip, lang, redis_conn, conversation_id)

    from voice.tools import lookups
    if name == "search_places":
        found = lookups.search_place(str(args.get("query") or ""), lang, show=args.get("show") is not False)
        if user_id and conversation_id and redis_conn is not None and found.place:
            from voice.tools import actions as A
            A.remember_place(redis_conn, user_id, conversation_id, found.place)
        return _from_tool(found)
    if name == "search_nearby":
        found = lookups.search_nearby(args.get("category"), args.get("near"), lang, near_me=args.get("near_me") is True,
                                      user_id=user_id, trip_id=trip.id if trip else None, origin=location)
        if user_id and conversation_id and redis_conn is not None and found.action == "map_results":
            from voice.tools import actions as A
            A.forget_place(redis_conn, user_id, conversation_id)   # a list: "yeh jagah save karo" must ask which
        return _from_tool(found)
    if name == "get_travel_time":
        return _from_tool(lookups.get_travel_time(str(args.get("place") or ""), args.get("mode"), lang, user_id=user_id,
                                                  trip_id=trip.id if trip else None, origin=location))
    if name == "get_weather":
        return _from_tool(lookups.get_weather(args.get("place"), args.get("day"), lang, user_id=user_id,
                                              trip_id=trip.id if trip else None))
    if not user_id:
        return _failed("no_user", {"stage": "tool", "tool": name, "detail": "missing user_id"})
    if name == "list_my_trips":
        return _from_tool(lookups.list_my_trips(user_id, lang, include_past=args.get("include_past") is True))
    if name == "open_trip":
        return _from_tool(lookups.open_trip(user_id, lang, name_or_destination=args.get("name_or_destination"),
                                            month=args.get("month"), which=args.get("which")))
    # answer_question
    from tour_guide_service import voice_answer
    ans = voice_answer(str(args.get("question") or "")[:500], lang, user_id=user_id,
                       trip_id=trip.id if trip else None, place=args.get("place"),
                       facts=args.get("facts") if isinstance(args.get("facts"), bool) else None)
    if ans["status"] == "ok":
        code = None if ans["source"] == "gemini_grounded" else f"answered_by_{ans['source']}:{ans.get('fallback_code')}"
        return AgentResult(ans["spoken"], action="answer", error_code=code, note=ans.get("note"))
    if ans["status"] == "declined":
        return AgentResult(ans["spoken"], action="decline", error_code="cost_guard")
    if ans["status"] == "no_facts":
        return AgentResult(ans["spoken"], action="answer", error_code=f"no_facts:{ans.get('fallback_code')}")
    return AgentResult(ANSWER_FAILED[lang], action="answer", error_code=f"answer_failed:{ans.get('fallback_code')}",
                       error_detail=f"answer tool failed: status={ans.get('status')} code={ans.get('fallback_code')}")


# ---------------- a bare acknowledgement with nothing open (BR-1006)

ACK_REPLY = {"hi": "Theek hai.", "en": "Okay."}
_ACK_MAX_WORDS = 6
_THANKS_WORDS = {canon(w) for w in (
    "dhanyavaad", "dhanyavad", "dhanyawad", "dhanyawaad", "shukriya", "sukriya", "thanks", "thank", "thankyou", "you",
    "u", "ok", "okay", "accha", "acha", "achha", "theek", "thik", "hai", "chalo", "bas", "ji", "haan", "han", "bhai",
    "sir", "bahut", "very", "much", "so", "great", "nice", "good", "badhiya", "perfect", "done", "cool", "fine",
    "धन्यवाद", "शुक्रिया", "थैंक", "थैंक्स", "यू", "ओके", "अच्छा", "ठीक", "है", "चलो", "बस", "जी", "हां", "भाई", "बहुत",
    "बढ़िया", "बढिया")}
# Words that make a short sentence a request, not a thank-you ("trip bana do", "shuru karo"): it goes to the model.
_REQUEST_WORDS = {canon(w) for w in (
    "bana", "banao", "banaiye", "karo", "kar", "kijiye", "shuru", "proceed", "confirm", "trip", "plan", "book", "booking",
    "बना", "बनाओ", "बनाइए", "करो", "कर", "कीजिए", "शुरू", "कन्फर्म", "ट्रिप", "प्लान", "बुक", "बुकिंग")}


def is_acknowledgement(text: str) -> bool:
    """Only a yes / thanks / ok ("हाँ, बिलकुल.", "हाँ, सही है", "धन्यवाद", "ok chalo"), short, with no request word."""
    from voice.confirm_words import is_positive_confirmation
    words = tu_words(text)
    if not words or len(words) > _ACK_MAX_WORDS or set(words) & _REQUEST_WORDS or any(ch.isdigit() for ch in text):
        return False                    # "500 hai" answers a question (the digits are not in words())
    return is_positive_confirmation(text) or set(words) <= _THANKS_WORDS


# ---------------- "change / add to / optimise / fix the open trip" (no voice tool does that)
# Evidence: with a Kolkata -> Bengaluru trip open, "...उस हिसाब से मेरा ट्रिप प्लान करो... इलेक्ट्रॉनिक सिटी",
# "रूट टूर पैकेज जो तुमने बनाया है, उसमें ही ये फिक्स करना है", "तेरह तारीख को मुझे ये ऐड करना है" started NEW trip drafts,
# and the model said it was updating the trip. Decided by CODE before the model call; a fixed reply, nothing changes.
# The reply names only controls that exist: the Swap and "Optimize Day N Route Flow" buttons on the trip screen and
# "Add to Itinerary" on map / Explore place cards.
EDIT_UNSUPPORTED_REPLY = {
    "hi": "Voice se trip ke andar badlav abhi nahi ho paata. Trip screen par Swap ya Optimize Day button se badal "
          "sakte hain, map se jagah Add to Itinerary kar sakte hain, ya main nayi trip bana sakta hoon.",
    "en": "I can't change an existing trip by voice yet. You can edit it on the trip screen with Swap or Optimize Day, "
          "add a place from the map with Add to Itinerary, or I can plan a new trip.",
}
_EDIT_WORDS = {canon(w) for w in (
    "add", "added", "adding", "jod", "jodo", "jodna", "jodiye", "jod", "badal", "badlo", "badalna", "badaliye", "badlna",
    "change", "changes", "update", "updated", "optimise", "optimize", "optimised", "optimized", "fix", "adjust", "set",
    "shift", "replace", "hata", "hatao", "hatado", "remove", "include", "shamil", "hisaab", "hisab", "according",
    "accordingly",
    "ऐड", "एड", "जोड़", "जोड़ो", "जोड़ना", "जोड़िए", "बदल", "बदलो", "बदलना", "बदलिए", "चेंज", "अपडेट", "ऑप्टिमाइज़",
    "ऑप्टिमाइज", "ऑप्टिमाइस", "फिक्स", "एडजस्ट", "सेट", "शिफ्ट", "रिप्लेस", "हटा", "हटाओ", "हटाना", "रिमूव", "शामिल",
    "इंक्लूड", "हिसाब")}
_TRIP_WORDS_EDIT = {canon(w) for w in (
    "trip", "trips", "itinerary", "plan", "route", "package", "tour",
    "ट्रिप", "इटिनरेरी", "प्लान", "रूट", "पैकेज", "टूर")}
_TRIP_POINTER_WORDS = {canon(w) for w in (     # "this / that one" = the open trip
    "isi", "isme", "ismein", "isko", "ise", "usme", "usmein", "usi", "ye", "yeh",
    "इसी", "इसमें", "इसमे", "इसको", "इसे", "उसमें", "उसमे", "उसी", "ये", "यह")}
_TRIP_POINTER_PHRASES = [tuple(tu_words(p)) for p in (
    "jo banaya", "jo bana", "jo tumne", "jo aapne", "जो बनाया", "जो बना", "जो तुमने", "जो आपने")]
_NEW_TRIP_PHRASES = [tuple(tu_words(p)) for p in (
    "nayi trip", "nai trip", "naya trip", "new trip", "ek aur trip", "another trip", "नई ट्रिप", "नयी ट्रिप", "नया ट्रिप",
    "एक और ट्रिप")]
# Requests that existing voice tools handle (weather replan, budget, expense, swap, regenerate, unsave): never this branch.
_OTHER_TOOL_WORDS = {canon(w) for w in (
    "baarish", "barish", "rain", "mausam", "weather", "budget", "kharcha", "kharch", "expense", "rupaye", "rupees", "rs",
    "hazaar", "hazar", "lakh", "swap", "instead", "dobara", "regenerate", "rebuild", "save", "saved",
    "बारिश", "मौसम", "वेदर", "बजट", "खर्च", "खर्चा", "रुपये", "रुपए", "हज़ार", "लाख", "स्वैप", "दोबारा", "सेव")}
_OTHER_TOOL_PHRASES = [tuple(tu_words(p)) for p in ("ki jagah", "की जगह", "phir se banao", "फिर से बनाओ")]
# A day named ("day 2 optimize karo", "kal ka plan badlo", "aaj ka route chhota karo"): weather_replan / optimize_day
# take a day, so these go to the model as before.
_DAY_WORDS = {canon(w) for w in ("day", "din", "aaj", "kal", "parso", "today", "tomorrow", "दिन", "आज", "कल", "परसों", "डे")}
# A bare "plan badlo" / "change the plan" with nothing else in it also goes to the model (weather_replan asks first).
# Fillers, and a plain "this / that" (it may mean the activity on screen), are not content.
_EDIT_FILLER = {canon(w) for w in (
    "ka", "ki", "ke", "ko", "mein", "me", "se", "par", "pe", "mera", "meri", "mere", "apna", "apni", "apne", "karo", "kar",
    "karna", "karni", "karke", "hai", "hain", "do", "de", "dijiye", "kijiye", "please", "plz", "thoda", "zara", "bhi",
    "hi", "aur", "and", "the", "my", "a", "an", "to", "it", "this", "can", "you", "ye", "yeh", "ise", "isko",
    "का", "की", "के", "को", "में", "से", "पर", "पे", "मेरा", "मेरी", "मेरे", "अपना", "अपनी", "करो", "कर", "करना", "करके",
    "है", "हैं", "दो", "दे", "दीजिए", "कीजिए", "थोड़ा", "ज़रा", "भी", "ही", "और", "ये", "यह", "इसे", "इसको")}


def _has_phrase(words: List[str], phrases) -> bool:
    return any(tuple(words[i:i + len(p)]) == p for p in phrases for i in range(len(words) - len(p) + 1))


def _names_open_trip(words: List[str], trip) -> bool:
    """The sentence names the open trip's city ("बैंगलोर" for "Bengaluru Tour Package"): consonant-skeleton match on
    the title's words, so Devanagari and spelling variants line up. Short names ("Goa") are not used (too loose)."""
    from voice.draft import name_matches, _skeleton
    title_words = [w for w in tu_words(getattr(trip, "title", "") or "")
                   if len(_skeleton(w)) >= 3 and canon(w) not in _TRIP_WORDS_EDIT]
    return any(name_matches(w, {"name": t}) for t in title_words for w in words if len(_skeleton(w)) >= 3)


def is_trip_edit_request(text: str, trip) -> bool:
    """A request to change, add to, optimise or fix the OPEN trip: an edit word plus a trip word, a pointer to the open
    trip ("isi", "usmein", "jo banaya") or its city. A new trip request or an existing tool's request is not one."""
    words = tu_words(text)
    ws = set(words)
    if not words or not (ws & _EDIT_WORDS):
        return False
    if _has_phrase(words, _NEW_TRIP_PHRASES) or ws & _OTHER_TOOL_WORDS or _has_phrase(words, _OTHER_TOOL_PHRASES):
        return False
    if ws & _DAY_WORDS or ws <= (_EDIT_WORDS | _TRIP_WORDS_EDIT | _EDIT_FILLER):
        return False
    return bool(ws & _TRIP_WORDS_EDIT or ws & _TRIP_POINTER_WORDS or _has_phrase(words, _TRIP_POINTER_PHRASES)
                or _names_open_trip(words, trip))


def _model_asked(redis_conn, user_id: str, conversation_id: str) -> bool:
    """The model's last reply in this conversation asked something ("Kitna budget hai?"): its answer goes to the model."""
    history = load_memory(redis_conn, user_id, conversation_id)
    last = next((m.get("content") or "" for m in reversed(history) if m.get("role") == "assistant"), "")
    return last.rstrip().endswith("?")


def _booking_open(redis_conn, user_id: str, trip) -> bool:
    """A booking flow still open for the open trip: its questions keep their usual handling (never an ack)."""
    trip_id = getattr(trip, "id", None) if trip is not None else None
    if not trip_id:
        return False
    try:
        import booking_flow as BF
        return BF.load(redis_conn, user_id, trip_id) is not None
    except Exception:
        return True                     # unsure: the model handles it as before


def _booking_turn(transcript: str, lang: str, user_id: str, conversation_id: str, trip, redis_conn):
    from voice import booking_voice
    return booking_voice.safe_handle(transcript, lang, user_id=user_id, conversation_id=conversation_id, trip=trip,
                                     redis_conn=redis_conn)


def run_agent(transcript: str, stt_language: Optional[str], *, user_id: str, conversation_id: str,
              screen: Optional[str], trip: Optional[TripInfo], redis_conn=None,
              screen_place: Optional[Dict[str, Any]] = None,
              location: Optional[Tuple[float, float]] = None, language: Optional[str] = None) -> AgentResult:
    """Blocking (HTTP): call from a threadpool. Never raises.
    language: the user's voice language (voice/languages.py). None / "auto" = as before (templates from the user's
    words, the model replies in the language spoken); a code = that language's templates and reply rule."""
    from openai_client import LLMError, LLMRateLimited, LLMTransient, chat_tools
    from voice import languages as L

    forced = L.template_lang(language, conversation_id)
    lang = forced or template_language(stt_language, transcript)
    if redis_conn is None:
        from redis_client import redis_conn as _r
        redis_conn = _r

    started = time.perf_counter()
    llm_done: Optional[float] = None
    used_llm = False
    from voice import draft as D, pending as P
    pending_conf = P.get(redis_conn, user_id, conversation_id)
    draft_state = D.load(redis_conn, user_id, conversation_id)
    skip_kind: Optional[str] = None
    said = yes_or_no(transcript)
    pending = pop_pending(redis_conn, user_id, conversation_id)
    answer_to_pending = said if pending else None
    result: Optional[AgentResult] = None
    trip_confirm_step = ((pending_conf is not None and pending_conf.get("tool") == "create_trip")
                         or (draft_state is not None and draft_state.awaiting == "date"))
    if said is None and trip_confirm_step:
        from voice.confirm_words import is_positive_confirmation
        if is_positive_confirmation(transcript):
            # "बना दो" / "हाँ, बना दो" / "ok chalo" at the read-back or the review page: the same as "haan" (no model call)
            said = "yes"
            print(f"[TRIP DRAFT] event=natural_yes source=voice draft={conversation_id}", flush=True)

    if pending_conf and said == "yes":
        # "haan" to the Confirm card: same action as the Confirm button.
        result = confirm_pending(redis_conn, user_id, conversation_id, lang,
                                 open_trip_id=trip.id if trip is not None and trip.id else None)
    elif pending_conf and said == "no":
        result = cancel_pending(redis_conn, user_id, conversation_id, lang)
    elif (draft_state is not None and draft_state.awaiting == "card"
          and not (said == "no" and _starts_cancel(transcript))):
        # A checked plan was offered: only a yes accepts; anything else declines (and is handled as usual).
        result = answer_plan_offer(redis_conn, user_id, conversation_id, draft_state,
                                   "yes" if plan_offer_yes(transcript) else said, lang)
        if result is None:
            draft_state = D.load(redis_conn, user_id, conversation_id)
    elif draft_state is not None and draft_state.awaiting == "date" and said == "yes":
        draft_state.dates_confirmed = True     # set only here, by code, after the read-back
        result = draft_next(redis_conn, user_id, conversation_id, draft_state, lang)
    elif draft_state is not None and draft_state.awaiting == "date" and said == "no":
        draft_state.start_date = draft_state.end_date = None
        draft_state.days = None
        draft_state.dates_confirmed = False
        draft_state.awaiting = None
        D.save(redis_conn, user_id, conversation_id, draft_state)
        result = AgentResult(DATE_AGAIN[lang], action="trip_draft", step="ask",
                             missing_count=len(draft_state.missing_fields()))
    elif draft_state is not None and said == "no" and _starts_cancel(transcript):
        result = cancel_trip(redis_conn, user_id, conversation_id, lang)
    elif draft_state is not None and (skip_kind := origin_skip_kind(
            transcript, draft_state.origin_pending or draft_state.awaiting == "origin_check")) == "short":
        result = skip_origin(redis_conn, user_id, conversation_id, draft_state, lang)   # no model call
    elif draft_state is not None and draft_state.awaiting in ("origin_same", "origin_check"):
        result = answer_origin_same(redis_conn, user_id, conversation_id, draft_state, said, lang)
        if result is None:
            draft_state = D.load(redis_conn, user_id, conversation_id)
    elif (draft_state is not None and (draft_state.purpose_pending or draft_state.area_pending)
          and not draft_state.origin_pending and is_purpose_area_skip(transcript)):
        result = skip_purpose_area(redis_conn, user_id, conversation_id, draft_state, lang)   # no model call
    elif (booking_result := _booking_turn(transcript, lang, user_id, conversation_id, trip, redis_conn)) is not None:
        result = booking_result      # booking stage 2: "book karwana hai" / an answer to the last booking question

    if result is not None:
        pass
    elif answer_to_pending == "yes":
        # "Taj Mahal kahan hai?" -> "... Map par dikhaun?" -> "haan": run the kept map actions, no LLM call.
        name = next((a.get("name") for a in pending if a.get("type") == "map_focus"), "")
        result = AgentResult({"hi": f"{name}: map par dikha diya.", "en": f"Showing {name} on the map."}[lang],
                             ui_actions=pending, action="map_focus")
    elif answer_to_pending == "no":
        result = AgentResult(OK_NO_REPLY[lang], action="reply")
    elif is_garbled(transcript):
        result = AgentResult(UNCLEAR_REPLY[lang], action="unclear", error_code="no_words")
    elif is_delete_request(transcript):
        result = delete_refused(lang)   # voice never deletes; no LLM call
    elif pending_conf is None and draft_state is None and is_acknowledgement(transcript)             and not _booking_open(redis_conn, user_id, trip) and not _model_asked(redis_conn, user_id, conversation_id):
        # BR-1006: "हाँ, बिलकुल." / "dhanyavaad" with nothing open to answer: a fixed reply, no model call.
        result = AgentResult(ACK_REPLY[lang], action="ack")
    elif (trip is not None and trip.id and draft_state is None and pending_conf is None
          and is_trip_edit_request(transcript, trip)):
        # "isi trip mein X add karo" with a trip open: no voice tool edits an itinerary. A fixed reply, no model call,
        # no draft, no navigation (a new trip request is not this branch).
        result = AgentResult(EDIT_UNSUPPORTED_REPLY[lang], action="edit_unsupported")
    else:
        from voice import context as trip_context
        if draft_state is not None and skip_kind is None:
            skip_kind = origin_skip_kind(transcript, draft_state.origin_pending or draft_state.awaiting == "origin_check")
        if draft_state is not None and skip_kind == "long":
            draft_state.skip_hint = True           # "pata nahi, Delhi se": a city the model extracts wins
            D.save(redis_conn, user_id, conversation_id, draft_state)
        trip_ctx = trip_context.load(user_id, trip.id) if trip is not None and trip.id else None
        messages: List[Dict[str, Any]] = [{"role": "system", "content": build_system_prompt(
            screen, trip, draft_line=_draft_line(draft_state), trip_context=trip_context.prompt_text(trip_ctx),
            reply_rule=L.reply_rule(language))}]
        messages += load_memory(redis_conn, user_id, conversation_id)
        messages.append({"role": "user", "content": transcript})
        used_llm = True
        attempt = 1
        tool_name: Optional[str] = None
        try:
            try:
                answer = chat_tools(messages, TOOLS, tool_choice="auto", temperature=0.2,
                                    timeout=LLM_TIMEOUT_SECONDS, reasoning_effort="low")
            except LLMTransient:
                # e.g. a 5xx, a timeout or a malformed tool call. One retry.
                attempt = 2
                answer = chat_tools(messages, TOOLS, tool_choice="auto", temperature=0.2,
                                    timeout=LLM_TIMEOUT_SECONDS, reasoning_effort="low")
            llm_done = time.perf_counter()
            tool_name = next((c.get("name") for c in answer["tool_calls"] if c.get("name") in TOOL_NAMES), None)
            result = _decide(answer["tool_calls"], answer["content"], lang, has_trip=trip is not None,
                             user_id=user_id, trip=trip, conversation_id=conversation_id, redis_conn=redis_conn,
                             trip_ctx=trip_ctx, screen_place=screen_place, location=location)
            if pending_conf and result.pending_confirmation is None and not result.action.startswith("trip_"):
                P.clear(redis_conn, user_id, conversation_id)   # a new topic cancels the pending confirmation
            if skip_kind == "long":
                after = D.load(redis_conn, user_id, conversation_id)
                if after is not None and after.skip_hint:   # the model didn't update the draft: the skip still counts
                    result = skip_origin(redis_conn, user_id, conversation_id, after, lang)
        # LLM errors carry status + provider code only (never the message, which can quote the user).
        except LLMRateLimited as err:
            result = _failed("rate_limited", llm_error_info(err, attempt), TRY_LATER_REPLY[lang])
        except LLMTransient as err:
            result = _failed("llm_transient_twice", llm_error_info(err, attempt))
        except LLMError as err:
            result = _failed("llm_error", llm_error_info(err, attempt), TRY_LATER_REPLY[lang])
        except Exception as err:
            # Unexpected (a bug, or a tool/lookup failing): the full traceback goes to the server log only.
            logger.exception("[VOICE AGENT] turn crashed in the agent")
            result = _failed(type(err).__name__, crash_error_info(err, tool_name))
    if forced == "en":    # the Hinglish-only lines, in English for a user who chose English
        result.reply_text = {FALLBACK_REPLY: FALLBACK_REPLY_EN, UNCLEAR_REPLY["en"]: UNCLEAR_REPLY_EN}.get(
            result.reply_text, result.reply_text)
    ended = time.perf_counter()
    result.llm_ms = int(((llm_done or ended) - started) * 1000) if used_llm else 0
    result.tool_ms = int((ended - llm_done) * 1000) if llm_done else (0 if used_llm else int((ended - started) * 1000))

    if result.pending_actions:
        save_pending(redis_conn, user_id, conversation_id, result.pending_actions)
    # booking answers (names, phone) stay out of the memory; so do acks and the trip confirm (memory just cleared)
    if result.action not in ("error", "booking", "ack", "trip_confirm", "edit_unsupported"):
        save_turn(redis_conn, user_id, conversation_id, transcript, result.reply_text)
    logger.info("[VOICE AGENT] action=%s%s%s llm_ms=%s tool_ms=%s%s%s%s", result.action,
                f" step={result.step}" if result.step else "",
                f" missing={result.missing_count}" if result.missing_count is not None else "",
                result.llm_ms, result.tool_ms, f" code={result.error_code}" if result.error_code else "",
                f" detail={result.error_detail}" if result.error_detail else "",
                f" google_calls={result.google_calls}" if result.google_calls is not None else "")
    return result
