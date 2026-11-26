"""
Create a trip by voice: the draft (voicefirst.md "Step 4 in detail").

The draft lives in Redis under voice:draft:{user}:{conversation} for 30 minutes after the last change, and is
deleted on confirm, cancel, end_session and when the socket closes. Nothing here creates a trip: when the draft
is ready, the app opens the review page (the existing wizard) with it as prefill, and only Proceed there (by tap,
or by "haan" / Confirm, which presses Proceed) saves, through the wizard's own path (trips:create ->
trip_lifecycle.create_trip_for_user). So edits made on the review page are what gets saved.

CODE decides what is missing and what to ask; the model only extracts values from what the user said.
Every value is checked and normalised here (dates in India time, integers for people, rupees for the budget,
places through the existing India-only place search).
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from trip_lifecycle import MIN_BUDGET_INR   # the one budget minimum, shared with trip creation

DRAFT_TTL_SECONDS = 30 * 60
MAX_DAYS = 30            # trip_lifecycle: at most 30 days
MAX_TRAVELERS = 20       # trip_lifecycle: at most 20 travelers
MAX_DAYS_AHEAD = 366
REQUIRED = ["destination", "start_date", "end_date", "adults", "children", "budget_inr"]  # the order we ask in

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
HINDI_NUMBERS = ["shunya", "ek", "do", "teen", "chaar", "paanch", "chhe", "saat", "aath", "nau", "das", "gyaarah", "baarah",
                 "terah", "chaudah", "pandrah", "solah", "satrah", "athaarah", "unnees", "bees", "ikkees", "baaees", "teyees",
                 "chaubees", "pachchees", "chhabbees", "sattaees", "atthaees", "unatees", "tees"]
_NUMBER_WORDS = {w: i for i, w in enumerate(HINDI_NUMBERS)}
_NUMBER_WORDS.update({"char": 4, "panch": 5, "chah": 6, "chhah": 6, "das": 10, "bis": 20, "pachas": 50, "pachaas": 50,
                      "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                      "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sau": 100, "hundred": 100})
_MULTIPLIERS = {"hazaar": 1000, "hazar": 1000, "hajar": 1000, "thousand": 1000, "k": 1000, "lakh": 100000, "lac": 100000,
                "lakhs": 100000, "crore": 10_000_000}


def _key(user_id: str, conversation_id: str) -> str:
    return f"voice:draft:{user_id}:{conversation_id}"


@dataclass
class TripDraftState:
    destination: Optional[Dict[str, Any]] = None   # DestinationReference (from the place search)
    origin_city: Optional[Dict[str, Any]] = None
    start_date: Optional[str] = None               # YYYY-MM-DD
    end_date: Optional[str] = None
    days: Optional[int] = None                     # "3 din ke liye" before a start date: kept until the start comes
    adults: Optional[int] = None
    children: Optional[int] = None
    budget_inr: Optional[int] = None
    dates_confirmed: bool = False                  # set ONLY by code, after the read-back got a yes
    awaiting: Optional[str] = None                 # "date" while the read-back waits for haan / a correction,
                                                   # "card" while a checked-plan offer waits for haan
    plan_offer_card: Optional[str] = None          # the checked plan (pilgrimage card id) offered for this destination
    plan_offer: Optional[str] = None               # None / "asked" / "accepted" / "declined": asked once per destination
    plan_card_id: Optional[str] = None             # set ONLY by code, after a yes to the offer

    def missing_fields(self) -> List[str]:
        return [f for f in REQUIRED if getattr(self, f) is None and not (f == "end_date" and self.days)]

    def next_step(self) -> str:
        if self.missing_fields():
            return "ask"
        if not self.dates_confirmed:
            return "confirm_date"
        return "ready"


# ---------------- Redis

def load(redis_conn, user_id: str, conversation_id: str) -> Optional[TripDraftState]:
    try:
        raw = redis_conn.get(_key(user_id, conversation_id))
        if not raw:
            return None
        data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        return TripDraftState(**{k: v for k, v in data.items() if k in TripDraftState.__dataclass_fields__})
    except Exception:
        return None


def save(redis_conn, user_id: str, conversation_id: str, draft: TripDraftState) -> None:
    redis_conn.setex(_key(user_id, conversation_id), DRAFT_TTL_SECONDS, json.dumps(asdict(draft)))


def delete(redis_conn, user_id: str, conversation_id: str) -> None:
    try:
        redis_conn.delete(_key(user_id, conversation_id))
    except Exception:
        pass


# ---------------- normalising values

def parse_int(raw: Any) -> Optional[int]:
    """2 / "2" / "do" / "two" / "koi nahi" (=0) -> int; None if it can't be read."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return int(raw) if float(raw) == int(raw) else None
    s = str(raw).strip().lower()
    if re.fullmatch(r"\d+", s):
        return int(s)
    if s in ("koi nahi", "koi bhi nahi", "none", "no", "nahi", "zero", "0", "koi bachcha nahi", "no kids"):
        return 0
    return _NUMBER_WORDS.get(s)


def parse_budget(raw: Any) -> Optional[int]:
    """50000 / "50000" / "50 hazaar" / "1.5 lakh" / "bees hazaar" / "₹45,000" -> rupees."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return int(round(raw))
    s = str(raw).strip().lower().replace(",", "").replace("₹", "").replace("rs", "").replace("rupaye", "").replace("rupees", "").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([a-z]+)?", s)
    if m:
        num = float(m.group(1))
        mult = _MULTIPLIERS.get(m.group(2) or "", 1 if not m.group(2) else None)
        return int(round(num * mult)) if mult else None
    words = s.split()
    if len(words) == 2 and words[0] in _NUMBER_WORDS and words[1] in _MULTIPLIERS:
        return _NUMBER_WORDS[words[0]] * _MULTIPLIERS[words[1]]
    return None


def parse_date(raw: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(raw).strip()[:10])
    except (TypeError, ValueError):
        return None


def say_date(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]}"


def nights_words(n: int, lang: str) -> str:
    if lang == "en":
        return f"{n} night{'s' if n != 1 else ''}"
    word = HINDI_NUMBERS[n] if 0 <= n < len(HINDI_NUMBERS) else str(n)
    return f"{word} raat"


@dataclass
class UpdateResult:
    draft: TripDraftState
    problems: List[str] = field(default_factory=list)   # short spoken reasons for refused values
    changed: List[str] = field(default_factory=list)


def apply_update(draft: TripDraftState, args: Dict[str, Any], lang: str, today: date, find_place_fn=None) -> UpdateResult:
    """Check and normalise each given field; refused values are not stored and come back as spoken reasons."""
    hi = lang != "en"
    out = UpdateResult(draft)
    if find_place_fn is None:
        from voice.tools.lookups import find_place as find_place_fn

    def place(raw: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        name = str(raw or "").strip()[:120]
        if len(name) < 2:
            return None, None
        hit = find_place_fn(name)
        if not hit:
            return None, (f"{name} nahi mila, India mein kaunsi jagah?" if hi else f"I couldn't find {name} in India. Which place?")
        from voice.tools.lookups import city_state
        city, state = city_state(hit)
        ref = {"id": hit.get("place_id") or hit.get("id"), "name": hit.get("name") or name, "city": city or hit.get("name"),
               "region": state, "country": "India", "latitude": float(hit["latitude"]), "longitude": float(hit["longitude"]),
               "displayName": hit.get("displayName") or hit.get("name") or name}
        return ref, None

    if args.get("destination"):
        ref, err = place(args["destination"])
        if ref:
            draft.destination = ref
            out.changed.append("destination")
        elif err:
            out.problems.append(err)
    if args.get("origin_city"):
        ref, err = place(args["origin_city"])
        if ref:
            draft.origin_city = ref
            out.changed.append("origin_city")
        elif err:
            out.problems.append(err)

    # Dates: start, end, or start + days. Checked together.
    start = parse_date(args.get("start_date")) if args.get("start_date") else (parse_date(draft.start_date) if draft.start_date else None)
    end = parse_date(args.get("end_date")) if args.get("end_date") else None
    days = parse_int(args.get("days"))
    if args.get("days") is not None and (days is None or not 1 <= days <= MAX_DAYS):
        out.problems.append("Trip 1 se 30 din ki ho sakti hai." if hi else "A trip can be 1 to 30 days.")
        days = None
    if args.get("start_date") and start is None:
        out.problems.append("Tareekh samajh nahi aayi." if hi else "I didn't get the date.")
    if days and start is None:
        draft.days = days            # remember the length; the end date comes with the start date
        draft.end_date = None
        draft.dates_confirmed = False
        out.changed.append("days")
    elif days is None and draft.days and start is not None and not args.get("end_date") and not draft.end_date:
        days = draft.days
    if end is None and days and start:
        end = start + timedelta(days=days - 1)
    if end is None and not args.get("end_date") and draft.end_date and args.get("start_date") and start:
        old_s, old_e = parse_date(draft.start_date), parse_date(draft.end_date)
        if old_s and old_e:
            end = start + (old_e - old_s)   # moving the start keeps the trip length
    if start is not None and (args.get("start_date") or args.get("end_date") or (days and not draft.end_date) or args.get("days")):
        if start < today:
            out.problems.append("Yeh tareekh beet chuki hai, aage ki tareekh boliye." if hi else "That date has passed. Please say a future date.")
        elif (start - today).days > MAX_DAYS_AHEAD:
            out.problems.append("Ek saal se aage ki trip abhi nahi ban sakti." if hi else "Trips can start at most a year ahead.")
        elif end is not None and end < start:
            out.problems.append("Wapsi ki tareekh jaane se pehle hai." if hi else "The end date is before the start date.")
        elif end is not None and (end - start).days + 1 > MAX_DAYS:
            out.problems.append("Trip zyada se zyada 30 din ki ho sakti hai." if hi else "A trip can be at most 30 days.")
        else:
            if start.isoformat() != draft.start_date or (end and end.isoformat() != draft.end_date):
                draft.dates_confirmed = False   # any date change needs a new read-back
            draft.start_date = start.isoformat()
            if end is not None:
                draft.end_date = end.isoformat()
                draft.days = None
            out.changed.append("dates")
    elif end is not None and start is None:
        out.problems.append("Pehle jaane ki tareekh boliye." if hi else "Please tell me the start date first.")

    for f, low in (("adults", 1), ("children", 0)):
        if f in args and args[f] is not None:
            n = parse_int(args[f])
            if n is None or n < low:
                out.problems.append(("Kam se kam ek bada hona chahiye." if hi else "At least one adult must travel.") if f == "adults"
                                    else ("Bachchon ki ginti samajh nahi aayi." if hi else "I didn't get the number of children."))
                continue
            setattr(draft, f, n)
            out.changed.append(f)
    if (draft.adults or 0) + (draft.children or 0) > MAX_TRAVELERS:
        out.problems.append(f"Ek trip mein zyada se zyada {MAX_TRAVELERS} log ho sakte hain." if hi else f"A trip can have at most {MAX_TRAVELERS} travelers.")
        draft.children = None if "children" in out.changed else draft.children
        draft.adults = None if "adults" in out.changed else draft.adults

    if args.get("budget_inr") is not None:
        b = parse_budget(args["budget_inr"])
        if b is None:
            out.problems.append("Budget samajh nahi aaya." if hi else "I didn't get the budget.")
        elif b < MIN_BUDGET_INR:
            out.problems.append(f"Budget kam se kam {MIN_BUDGET_INR} rupaye hona chahiye." if hi
                                else f"The budget must be at least ₹{MIN_BUDGET_INR:,}.")
        else:
            draft.budget_inr = b
            out.changed.append("budget_inr")
    return out


# ---------------- what to say

QUESTIONS = {
    "destination": {"hi": "Kahan jaana hai?", "en": "Where do you want to go?"},
    "start_date": {"hi": "Kab se kab tak jaana hai?", "en": "From which date to which date?"},
    "end_date": {"hi": "Kab tak ki trip hai?", "en": "Until which date?"},
    "adults": {"hi": "Kitne bade log jaa rahe hain?", "en": "How many adults are going?"},
    "children": {"hi": "Koi bachcha bhi saath hai?", "en": "Any children coming along?"},
    "budget_inr": {"hi": "Kul budget kitna hai?", "en": "What's the total budget?"},
}


def question_for(missing: List[str], lang: str, days_known: bool = False) -> str:
    """At most 2 missing fields per question; the date pair counts as one."""
    lang = "en" if lang == "en" else "hi"
    fields = [f for f in missing if not (f == "end_date" and "start_date" in missing)][:2]
    parts = []
    for f in fields:
        if f == "start_date" and days_known:
            parts.append({"hi": "Kab se jaana hai?", "en": "From which date?"}[lang])
        else:
            parts.append(QUESTIONS[f][lang])
    return " ".join(parts)


def readback(draft: TripDraftState, lang: str) -> str:
    s, e = parse_date(draft.start_date), parse_date(draft.end_date)
    nights = max((e - s).days, 0)
    if lang == "en":
        return f"{say_date(s)} to {say_date(e)}, {nights_words(nights, 'en')}. Is that right?"
    return f"{say_date(s)} se {say_date(e)}, {nights_words(nights, 'hi')}. Sahi hai?"


def summary(draft: TripDraftState, lang: str) -> str:
    """The confirm card's text. Says that creating a trip can't be undone by voice."""
    s, e = parse_date(draft.start_date), parse_date(draft.end_date)
    dest = (draft.destination or {}).get("name", "")
    who = f"{draft.adults} adult{'s' if draft.adults != 1 else ''}" + (f", {draft.children} child{'ren' if draft.children != 1 else ''}" if draft.children else "")
    origin = f" from {(draft.origin_city or {}).get('name')}" if draft.origin_city else ""
    if draft.plan_card_id:
        import pilgrimage
        card = pilgrimage.get_card(draft.plan_card_id)
        dest = f"{dest} ({card.short_name}, checked plan)" if card else dest
    if lang == "en":
        return (f"{dest}{origin}, {say_date(s)} to {say_date(e)}, {who}, budget ₹{draft.budget_inr:,}. "
                "Confirm saves what's on the review page. A trip can't be undone by voice.")
    return (f"{dest}{origin}, {say_date(s)} se {say_date(e)}, {who}, budget ₹{draft.budget_inr:,}. "
            "Confirm review page ki details save karega. Trip voice se undo nahi hogi.")


def prefill(draft: TripDraftState) -> Dict[str, Any]:
    """The wizard's TripDraft shape (frontend/src/features/trip/types.ts)."""
    return {
        "destination": draft.destination,
        "origin": draft.origin_city,
        "startDate": draft.start_date,
        "endDate": draft.end_date,
        "adultsCount": draft.adults,
        "childrenCount": draft.children,
        "customBudgetAmount": draft.budget_inr,
        **({"planCardId": draft.plan_card_id} if draft.plan_card_id else {}),
    }
