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
from difflib import SequenceMatcher
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from trip_lifecycle import MIN_BUDGET_INR   # the one budget minimum, shared with trip creation
from trip_lifecycle import clean_place_name  # the one starting-city name rule, shared with trip creation
from voice.text_utils import canon, words as tu_words
from voice import bn_words as BN
from voice.bn_words import BN_MONTHS
from voice.languages import tkey

DRAFT_TTL_SECONDS = 30 * 60
MAX_DAYS = 30            # trip_lifecycle: at most 30 days
MAX_TRAVELERS = 20       # trip_lifecycle: at most 20 travelers
MAX_DAYS_AHEAD = 366
REQUIRED = ["destination", "start_date", "end_date", "adults", "children", "budget_inr"]  # the order we ask in
MAX_QUESTIONS = 2        # questions per turn (the date pair counts once); the optional origin only fills a free slot
MAX_ORIGIN_ASKS = 2      # the origin question plus one retry after a failed lookup: never a third time
MAX_AREA_ASKS = 2        # the base area question plus one retry after a failed lookup, like the origin

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
    # The optional starting city. Kept in the draft (Redis) so a retry never asks the same question a third time.
    origin_asked: int = 0                          # times we asked for it (question or retry), at most MAX_ORIGIN_ASKS
    origin_pending: bool = False                   # our last question asked for it: the next answer decides
    origin_failed: int = 0                         # lookups that found nothing
    origin_skipped: bool = False                   # "pata nahi" / not given when asked / second failed lookup
    origin_same_ok: bool = False                   # the user said yes to "origin = destination?"
    last_asked: List[str] = field(default_factory=list)   # fields our last question asked for (for the prompt)
    origin_candidate: Optional[Dict[str, Any]] = None  # a looked-up city whose name doesn't match what was said:
                                                   # "<name> se? Sahi hai?" (asked once) before it becomes the origin
    origin_checked: bool = False                   # that check was asked once already: never a second time
    skip_hint: bool = False                        # this turn's words said "don't know where from" (set by code)
    # The optional purpose ("Kis kaam se ja rahe hain?") and, for business / event / other, the base area
    # ("Kis area mein zyada rehna ya kaam hai?"). Same discipline as the origin: asked once, after it, in a free slot.
    purpose_type: Optional[str] = None             # trip_purpose.PURPOSE_TYPES, set ONLY by code from the words
    purpose_text: Optional[str] = None             # the user's words (business / event / other), checked by code
    purpose_asked: int = 0
    purpose_pending: bool = False                  # our last question asked for it
    purpose_skipped: bool = False                  # "pata nahi" / not given when asked
    base_area: Optional[Dict[str, Any]] = None     # {id, name, city, region, latitude, longitude}, near the destination
    area_asked: int = 0                            # question or retry, at most MAX_AREA_ASKS
    area_pending: bool = False
    area_failed: int = 0
    area_skipped: bool = False

    def missing_fields(self) -> List[str]:
        return [f for f in REQUIRED if getattr(self, f) is None and not (f == "end_date" and self.days)]

    def wants_origin(self) -> bool:
        """Ask for the starting city? Only once, and never after a skip."""
        return self.origin_city is None and not self.origin_skipped and self.origin_asked == 0

    def wants_purpose(self) -> bool:
        """Ask why? Once, after the origin question, never after a skip, never for a checked plan (a pilgrimage)."""
        return (self.purpose_type is None and not self.purpose_skipped and self.purpose_asked == 0
                and not self.wants_origin() and not self.plan_card_id)

    def wants_area(self) -> bool:
        """Ask where they will mostly be? Only for business / event / other, once (plus one retry after a miss)."""
        from trip_purpose import is_focused
        return (is_focused(self.purpose_type) and self.base_area is None and not self.area_skipped
                and self.area_asked == 0)

    def origin_is_destination(self) -> bool:
        return (not self.origin_same_ok) and same_place(self.origin_city, self.destination)

    def next_step(self) -> str:
        if self.missing_fields() or self.wants_origin() or self.wants_purpose() or self.wants_area():
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
    found = _NUMBER_WORDS.get(s)
    return found if found is not None else BN.number(s)     # Bengali number words ("পঁচিশ", "দুটো", "কেউ নেই")


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
    return BN.budget(raw)     # Bengali: "পঞ্চাশ হাজার", "৫০ হাজার", "1.5 লাখ"


def parse_date(raw: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(raw).strip()[:10])
    except (TypeError, ValueError):
        return None


# ---------------- dates as spoken ("पच्चीस तारीख" = the NEXT 25th, never a past one the model assumed)

def _months_from(year: int, month: int, count: int):
    for i in range(count):
        m = month - 1 + i
        yield year + m // 12, m % 12 + 1


def _try_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def resolve_said_date(day: int, month: Optional[int], year: Optional[int], not_before: date) -> Optional[date]:
    """The date a person means from the parts they SAID, as the first matching date on or after `not_before`:
    - day only: this month if not passed, else the next month that HAS that day (31 skips short months), next year
      if needed;
    - day + month: the next occurrence (next year if passed this year);
    - with a year: exactly that date (a past one is refused by the caller, as before).
    None if no such date exists (e.g. day 32, 30 February 2027)."""
    if not 1 <= day <= 31 or (month is not None and not 1 <= month <= 12):
        return None
    if year is not None:
        if month is not None:
            return _try_date(year, month, day)
        start_month = not_before.month if year == not_before.year else 1
        found = [d for y, m in _months_from(year, start_month, 13 - start_month) if (d := _try_date(y, m, day))]
        future = [d for d in found if d >= not_before]
        return (future or found or [None])[0]
    if month is not None:
        for y in range(not_before.year, not_before.year + 9):   # 29 February: the next leap year
            d = _try_date(y, month, day)
            if d and d >= not_before:
                return d
        return None
    for y, m in _months_from(not_before.year, not_before.month, 14):
        d = _try_date(y, m, day)
        if d and d >= not_before:
            return d
    return None


def _said_parts(args: Dict[str, Any], which: str) -> Optional[Tuple[int, Optional[int], Optional[int]]]:
    day = parse_int(args.get(f"{which}_day"))
    if day is None:
        return None
    month, year = parse_int(args.get(f"{which}_month")), parse_int(args.get(f"{which}_year"))
    if month is None and args.get(f"{which}_month") is not None:
        month = BN.month(args.get(f"{which}_month"))      # a Bengali month name ("ডিসেম্বর")
    return day, month, year


def say_date(d: date, lang: Optional[str] = None) -> str:
    """"12 December" (hi / en, as before); Bengali: "12 ডিসেম্বর"."""
    if lang == "bn":
        return f"{d.day} {BN_MONTHS[d.month - 1]}"
    return f"{d.day} {MONTHS[d.month - 1]}"


def nights_words(n: int, lang: str) -> str:
    if lang == "en":
        return f"{n} night{'s' if n != 1 else ''}"
    if lang == "bn":
        return f"{n} রাত"
    word = HINDI_NUMBERS[n] if 0 <= n < len(HINDI_NUMBERS) else str(n)
    return f"{word} raat"


# ---------------- the starting city: words that are never a city, and "does the found place match what was said?"

# The model sometimes returns these as the origin ("पता।" -> origin "पता" -> Google: Patna). Checked by code before
# any Google lookup; an origin made only of these words is "not given".
NOT_A_CITY_WORDS = {canon(w) for w in (
    "pata", "patah", "nahi", "nahin", "nai", "na", "kuch", "kuchh", "koi", "kahin", "kahi", "kahan", "kahaan", "maloom",
    "malum", "chhodo", "chodo", "chhod", "chod", "chhodiye", "do", "skip", "abhi", "baad", "mein", "se", "mujhe", "yaar",
    "hai", "jaana", "jagah", "shahar", "starting", "city", "origin", "i", "don", "t", "dont", "know", "no", "idea", "not",
    "sure", "none", "nothing", "unknown", "bhi", "भी",
    "पता", "नहीं", "ना", "कुछ", "कोई", "कहीं", "कहां", "मालूम", "छोड़ो", "छोड़", "छोड़िए", "दो", "स्किप", "अभी", "बाद", "में",
    "से", "मुझे", "यार", "है", "जाना", "जगह", "शहर",
    # Bengali (beta)
    "জানি", "না", "কিছু", "কোনো", "কোথাও", "কোথায়", "বাদ", "পরে", "এখন", "আমি", "আমার", "শহর", "জায়গা", "থেকে")}


def is_not_a_city(raw: Any) -> bool:
    ws = tu_words(str(raw or ""))
    return bool(ws) and all(w in NOT_A_CITY_WORDS for w in ws)


# Name check: compare consonant skeletons, so Devanagari, Latin and spelling variants line up
# (पटना / Patna -> "ptn", कोलकाता / Kolkata / Calcutta -> "klkt"); vowels, h/v/w/y and doubled letters are ignored.
_DEV_CONSONANTS = {"क": "k", "ख": "k", "ग": "g", "घ": "g", "ङ": "n", "च": "c", "छ": "c", "ज": "j", "झ": "j", "ञ": "n",
                   "ट": "t", "ठ": "t", "ड": "d", "ढ": "d", "ण": "n", "त": "t", "थ": "t", "द": "d", "ध": "d", "न": "n",
                   "प": "p", "फ": "f", "ब": "b", "भ": "b", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "s",
                   "ष": "s", "स": "s", "ह": "h", "ळ": "l"}
# Latin spellings -> the same letters (order matters: "chh"/"ch" are kept as c, a lone c is k as in "Calcutta").
_LATIN_PAIRS = (("chh", "C"), ("ch", "C"), ("sh", "s"), ("th", "t"), ("dh", "d"), ("bh", "b"), ("kh", "k"), ("gh", "g"),
                ("jh", "j"), ("ph", "f"), ("c", "k"), ("C", "c"), ("q", "k"), ("z", "j"), ("x", "ks"))


def _skeleton(text: str) -> str:
    out = []
    for w in tu_words(text):
        if any("\u0900" <= ch <= "\u097f" for ch in w):
            out.extend(_DEV_CONSONANTS.get(ch, "") for ch in w)
        else:
            w = re.sub(r"[^a-z]", "", w)
            for a, b in _LATIN_PAIRS:
                w = w.replace(a, b)
            out.append(w)
    sk = re.sub(r"[aeiouhvwy]", "", "".join(out))
    return re.sub(r"(.)\1+", r"\1", sk)


def name_matches(said: str, place_ref: Dict[str, Any]) -> bool:
    """Does the found place plausibly match what was said? Same first consonant and similar skeletons, against the
    place's name, its city, or one word of the name ("Delhi" -> "New Delhi")."""
    a = _skeleton(said)
    if not a:
        return False
    names = [str(place_ref.get(k) or "") for k in ("name", "city")]
    names += [w for n in names for w in n.split() if len(w) >= 3]
    for n in names:
        b = _skeleton(n)
        if b and (a == b or (a[0] == b[0] and SequenceMatcher(None, a, b).ratio() >= 0.65)):
            return True
    return False


def same_place(a: Optional[Dict[str, Any]], b: Optional[Dict[str, Any]]) -> bool:
    if not a or not b:
        return False
    if a.get("id") and a.get("id") == b.get("id"):
        return True
    names = lambda p: {str(p.get(k) or "").strip().lower() for k in ("name", "city")} - {""}  # noqa: E731
    return bool(names(a) & names(b))


@dataclass
class UpdateResult:
    draft: TripDraftState
    problems: List[str] = field(default_factory=list)   # short spoken reasons for refused values
    changed: List[str] = field(default_factory=list)
    origin_not_found: Optional[str] = None               # a valid name that the place search did not find
    origin_invalid: bool = False                         # not a place name (digits, too long, ...): not given
    origin_stopword: bool = False                        # "pata" / "पता" / "nahi" ...: not a city, no Google call
    date_rolled_forward: bool = False                    # a day (and month) without a year/month became a future date
    date_fields_missing: bool = False                    # the model sent only an ISO date (no as-spoken fields)
    origin_unsure: bool = False                          # found, but the name doesn't match what was said
    purpose_skip: bool = False                           # "pata nahi" / "kuch nahi" as the purpose
    area_not_found: Optional[str] = None                 # a valid area name not found near the destination
    area_invalid: bool = False                           # not a place name / "pata nahi": not given


def apply_purpose(draft: TripDraftState, said: Any, out: UpdateResult) -> None:
    """The words about WHY -> a type by CODE (trip_purpose word lists). A skip says "not given"; a new type after the
    read-back needs a new read-back (it names the purpose). Leisure / pilgrimage drop a base area."""
    from trip_purpose import classify_purpose, is_focused
    ptype, ptext, skipped = classify_purpose(said)
    if skipped:
        out.purpose_skip = True
        if draft.purpose_type is None:
            draft.purpose_skipped = True
        return
    if ptype is None:
        return
    if (ptype, ptext) != (draft.purpose_type, draft.purpose_text):
        draft.dates_confirmed = False
        out.changed.append("purpose")
    draft.purpose_type, draft.purpose_text, draft.purpose_skipped = ptype, ptext, False
    if not is_focused(ptype):
        draft.base_area = None


def apply_base_area(draft: TripDraftState, said: Any, out: UpdateResult, find_place_fn) -> None:
    """The area the user will mostly be in: the same name rule and Google look-up as the origin, searched next to the
    destination, kept only within the place-verify sanity radius of it."""
    from trip_purpose import area_ref, base_area_ok
    name = clean_place_name(said)
    if not name or is_not_a_city(name):
        out.area_invalid = True
        return
    dest = draft.destination or {}
    city = str(dest.get("city") or dest.get("name") or "").split(",")[0].strip()
    query = f"{name}, {city}" if city and city.lower() not in name.lower() else name
    hit = find_place_fn(query)
    ref = area_ref(hit, name) if hit else None
    if ref is None or not base_area_ok(ref, dest):
        out.area_not_found = name
        return
    if (draft.base_area or {}).get("id") != ref.get("id"):
        draft.dates_confirmed = False
        out.changed.append("base_area")
    draft.base_area, draft.area_skipped = ref, False


# Why a value was refused (spoken). The same words as before for hi / en; bn (beta) for Bengali.
PROBLEMS = {
    "place_not_found": {"hi": "{name} nahi mila, India mein kaunsi jagah?", "en": "I couldn't find {name} in India. Which place?",
                        "bn": "ভারতে {name} খুঁজে পেলাম না। কোন জায়গা?"},
    "date_unclear": {"hi": "Tareekh samajh nahi aayi.", "en": "I didn't get the date.", "bn": "তারিখটা বুঝতে পারলাম না।"},
    "days_range": {"hi": "Trip 1 se 30 din ki ho sakti hai.", "en": "A trip can be 1 to 30 days.",
                   "bn": "ট্রিপ 1 থেকে 30 দিনের হতে পারে।"},
    "past_date": {"hi": "Yeh tareekh beet chuki hai, aage ki tareekh boliye.",
                  "en": "That date has passed. Please say a future date.",
                  "bn": "এই তারিখটা পেরিয়ে গেছে। সামনের কোনো তারিখ বলুন।"},
    "too_far_ahead": {"hi": "Ek saal se aage ki trip abhi nahi ban sakti.", "en": "Trips can start at most a year ahead.",
                      "bn": "এক বছরের বেশি পরের ট্রিপ এখন বানানো যাবে না।"},
    "end_before_start": {"hi": "Wapsi ki tareekh jaane se pehle hai.", "en": "The end date is before the start date.",
                         "bn": "ফেরার তারিখটা যাওয়ার তারিখের আগে পড়ছে।"},
    "too_long": {"hi": "Trip zyada se zyada 30 din ki ho sakti hai.", "en": "A trip can be at most 30 days.",
                 "bn": "ট্রিপ সর্বোচ্চ 30 দিনের হতে পারে।"},
    "start_first": {"hi": "Pehle jaane ki tareekh boliye.", "en": "Please tell me the start date first.",
                    "bn": "আগে যাওয়ার তারিখটা বলুন।"},
    "adults_min": {"hi": "Kam se kam ek bada hona chahiye.", "en": "At least one adult must travel.",
                   "bn": "অন্তত একজন প্রাপ্তবয়স্ক থাকতে হবে।"},
    "children_unclear": {"hi": "Bachchon ki ginti samajh nahi aayi.", "en": "I didn't get the number of children.",
                         "bn": "বাচ্চাদের সংখ্যাটা বুঝতে পারলাম না।"},
    "too_many": {"hi": "Ek trip mein zyada se zyada {n} log ho sakte hain.", "en": "A trip can have at most {n} travelers.",
                 "bn": "একটা ট্রিপে সর্বোচ্চ {n} জন যেতে পারেন।"},
    "budget_unclear": {"hi": "Budget samajh nahi aaya.", "en": "I didn't get the budget.", "bn": "বাজেটটা বুঝতে পারলাম না।"},
    "budget_min": {"hi": "Budget kam se kam {n} rupaye hona chahiye.", "en": "The budget must be at least ₹{n:,}.",
                   "bn": "বাজেট অন্তত ₹{n:,} হতে হবে।"},
}


def apply_update(draft: TripDraftState, args: Dict[str, Any], lang: str, today: date, find_place_fn=None) -> UpdateResult:
    """Check and normalise each given field; refused values are not stored and come back as spoken reasons."""
    k = tkey(lang)
    out = UpdateResult(draft)
    if find_place_fn is None:
        from voice.tools.lookups import find_place as find_place_fn

    def place(raw: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        name = str(raw or "").strip()[:120]
        if len(name) < 2:
            return None, None
        hit = find_place_fn(name)
        if not hit:
            return None, PROBLEMS["place_not_found"][k].format(name=name)
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
    if args.get("origin_city") is not None and args.get("origin_city") != "":
        name = clean_place_name(args["origin_city"])   # code checks what the model extracted
        if name and is_not_a_city(name):
            name, out.origin_stopword = None, True       # "pata" is not a city: discarded before any Google call
        ref = place(name)[0] if name else None
        if ref and not draft.origin_checked and (draft.origin_city or {}).get("id") != ref.get("id") \
                and not name_matches(name, ref):
            draft.origin_candidate, draft.origin_checked = ref, True   # "<name> se? Sahi hai?" once
            draft.origin_skipped = False
            out.origin_unsure = True
        elif ref:
            if (draft.origin_city or {}).get("id") != ref.get("id"):
                draft.dates_confirmed = False   # the read-back says the origin, so it must be read back again
                draft.origin_same_ok = False
                out.changed.append("origin_city")
            draft.origin_city, draft.origin_candidate = ref, None
            draft.origin_skipped = False
        elif out.origin_stopword:
            out.origin_invalid = True
        elif name:
            out.origin_not_found = name
        else:
            out.origin_invalid = True

    if args.get("purpose") not in (None, ""):
        apply_purpose(draft, args["purpose"], out)
    if args.get("base_area") not in (None, ""):
        apply_base_area(draft, args["base_area"], out, find_place_fn)

    # Dates as spoken: the model passes only the parts the user said; CODE picks the month / year (rolling forward).
    # Without these fields the model's ISO date is used as before (a past one is refused; code never guesses).
    said_start, said_end = _said_parts(args, "start"), _said_parts(args, "end")
    if said_start or said_end:
        args = dict(args)
        bad = False
        s_res = None
        if said_start:
            day, month, year = said_start
            s_res = resolve_said_date(day, month, year, today)
            if s_res is None:
                bad = True
            else:
                args["start_date"] = s_res.isoformat()
                naive = _try_date(year or today.year, month or today.month, day)
                out.date_rolled_forward = year is None and naive != s_res
        if said_end and not bad:
            day, month, year = said_end
            if said_start and month is None and said_start[1] is not None and year is None:
                month = said_start[1]      # "25 December se 27" -> 27 December
            base = s_res or parse_date(draft.start_date) or today
            e_res = resolve_said_date(day, month, year, base) if year is None else _try_date(year, month or base.month, day)
            if e_res is None:
                bad = True
            else:
                args["end_date"] = e_res.isoformat()
        if bad:
            out.problems.append(PROBLEMS["date_unclear"][k])
            args.pop("start_date", None)
            args.pop("end_date", None)
    elif args.get("start_date") or args.get("end_date"):
        out.date_fields_missing = True

    # Dates: start, end, or start + days. Checked together.
    start = parse_date(args.get("start_date")) if args.get("start_date") else (parse_date(draft.start_date) if draft.start_date else None)
    end = parse_date(args.get("end_date")) if args.get("end_date") else None
    days = parse_int(args.get("days"))
    if args.get("days") is not None and (days is None or not 1 <= days <= MAX_DAYS):
        out.problems.append(PROBLEMS["days_range"][k])
        days = None
    if args.get("start_date") and start is None:
        out.problems.append(PROBLEMS["date_unclear"][k])
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
            out.problems.append(PROBLEMS["past_date"][k])
        elif (start - today).days > MAX_DAYS_AHEAD:
            out.problems.append(PROBLEMS["too_far_ahead"][k])
        elif end is not None and end < start:
            out.problems.append(PROBLEMS["end_before_start"][k])
        elif end is not None and (end - start).days + 1 > MAX_DAYS:
            out.problems.append(PROBLEMS["too_long"][k])
        else:
            if start.isoformat() != draft.start_date or (end and end.isoformat() != draft.end_date):
                draft.dates_confirmed = False   # any date change needs a new read-back
            draft.start_date = start.isoformat()
            if end is not None:
                draft.end_date = end.isoformat()
                draft.days = None
            out.changed.append("dates")
    elif end is not None and start is None:
        out.problems.append(PROBLEMS["start_first"][k])

    for f, low in (("adults", 1), ("children", 0)):
        if f in args and args[f] is not None:
            n = parse_int(args[f])
            if n is None or n < low:
                out.problems.append(PROBLEMS["adults_min"][k] if f == "adults" else PROBLEMS["children_unclear"][k])
                continue
            setattr(draft, f, n)
            out.changed.append(f)
    if (draft.adults or 0) + (draft.children or 0) > MAX_TRAVELERS:
        out.problems.append(PROBLEMS["too_many"][k].format(n=MAX_TRAVELERS))
        draft.children = None if "children" in out.changed else draft.children
        draft.adults = None if "adults" in out.changed else draft.adults

    if args.get("budget_inr") is not None:
        b = parse_budget(args["budget_inr"])
        if b is None:
            out.problems.append(PROBLEMS["budget_unclear"][k])
        elif b < MIN_BUDGET_INR:
            out.problems.append(PROBLEMS["budget_min"][k].format(n=MIN_BUDGET_INR))
        else:
            draft.budget_inr = b
            out.changed.append("budget_inr")
    return out


# ---------------- what to say

QUESTIONS = {
    "destination": {"hi": "Kahan jaana hai?", "en": "Where do you want to go?", "bn": "কোথায় যেতে চান?"},
    "start_date": {"hi": "Kab se kab tak jaana hai?", "en": "From which date to which date?", "bn": "কোন তারিখ থেকে কোন তারিখ পর্যন্ত যাবেন?"},
    "end_date": {"hi": "Kab tak ki trip hai?", "en": "Until which date?", "bn": "কোন তারিখ পর্যন্ত ট্রিপ?"},
    "adults": {"hi": "Kitne bade log jaa rahe hain?", "en": "How many adults are going?", "bn": "কতজন প্রাপ্তবয়স্ক যাচ্ছেন?"},
    "children": {"hi": "Koi bachcha bhi saath hai?", "en": "Any children coming along?", "bn": "সঙ্গে কোনো বাচ্চা আছে?"},
    "budget_inr": {"hi": "Kul budget kitna hai?", "en": "What's the total budget?", "bn": "মোট বাজেট কত?"},
    "origin_city": {"hi": "Kahan se jaana hai?", "en": "Where are you starting from?", "bn": "কোথা থেকে যাবেন?"},
    "purpose": {"hi": "Kis kaam se ja rahe hain? Ghoomna, kaam ya business, event ya hackathon, teerth, ya kuch aur?",
                "en": "What's the trip for? A holiday, work or business, an event like a hackathon, a pilgrimage, "
                      "or something else?", "bn": "কী কাজে যাচ্ছেন? বেড়াতে, অফিসের কাজে বা বিজনেসে, হ্যাকাথনের মতো কোনো ইভেন্টে, তীর্থে, নাকি অন্য কিছু?"},
    "base_area": {"hi": "Kis area mein zyada rehna ya kaam hai? Jaise Electronic City.",
                  "en": "Which area will you mostly be in? For example Electronic City.", "bn": "কোন এলাকায় বেশি থাকবেন বা কাজ করবেন? যেমন Electronic City।"},
}
AREA_RETRY = {"hi": "{name} {city} ke paas nahi mila, area ka naam phir se bolenge ya skip karein?",
              "en": "I couldn't find {name} near {city}. Say the area again, or say skip?", "bn": "{city}-এর কাছে {name} খুঁজে পেলাম না। এলাকার নামটা আবার বলবেন, নাকি স্কিপ করবেন?"}
AREA_GIVE_UP = {"hi": "{name} bhi nahi mila, area ke bina aage badhte hain.",
                "en": "I couldn't find {name} either, so we'll go on without an area.", "bn": "{name}-ও খুঁজে পেলাম না, এলাকা ছাড়াই এগোচ্ছি।"}
PURPOSE_SKIPPED = {"hi": "", "en": "", "bn": ""}   # "pata nahi" to the purpose / area question: straight on (the read-back follows)
# How the read-back says the purpose when the user's own word isn't known ("kaam ke liye"); with it, the word.
PURPOSE_WORDS = {
    "leisure": {"hi": "ghoomne ke liye", "en": "for a holiday", "bn": "বেড়ানোর জন্য"},
    "business": {"hi": "kaam ke liye", "en": "for work", "bn": "কাজের জন্য"},
    "event": {"hi": "event ke liye", "en": "for an event", "bn": "ইভেন্টের জন্য"},
    "pilgrimage": {"hi": "teerth ke liye", "en": "for a pilgrimage", "bn": "তীর্থের জন্য"},
    "other": {"hi": "aapke bataye kaam ke liye", "en": "for the reason you gave", "bn": "আপনার বলা কারণে"},
}
_SAY_TEXT_MAX = 30
# The user's own purpose word ("hackathon ke liye") and the base area (", Electronic City ke paas") in the read-back.
OWN_PURPOSE = {"hi": "{text} ke liye", "en": "for your {text}", "bn": "আপনার {text}-এর জন্য"}
NEAR_AREA = {"hi": ", {area} ke paas", "en": ", near {area}", "bn": ", {area}-এর কাছে"}
# The read-back of the dates (step 4): with a starting city, and without.
READBACK_FROM = {"hi": "{frm} se {to}, {start} se {end}, {nights}, {who}{why}. Sahi hai?",
                 "en": "{frm} to {to}, {start} to {end}, {nights}, {who}{why}. Is that right?",
                 "bn": "{frm} থেকে {to}, {start} থেকে {end}, {nights}, {who}{why}। ঠিক আছে?"}
READBACK = {"hi": "{start} se {end}, {nights}{why}. Sahi hai?",
            "en": "{start} to {end}, {nights}{why}. Is that right?",
            "bn": "{start} থেকে {end}, {nights}{why}। ঠিক আছে?"}
# The Confirm card's text. who / origin stay as before (English words) in every language.
SUMMARY = {"hi": "{dest}{origin}, {start} se {end}, {who}, budget ₹{budget:,}. Confirm review page ki details save karega. "
                 "Trip voice se undo nahi hogi.",
           "en": "{dest}{origin}, {start} to {end}, {who}, budget ₹{budget:,}. Confirm saves what's on the review page. "
                 "A trip can't be undone by voice.",
           "bn": "{dest}{origin}, {start} থেকে {end}, {who}, বাজেট ₹{budget:,}। Confirm চাপলে রিভিউ পেজের তথ্য সেভ হবে। "
                 "ভয়েস দিয়ে ট্রিপ আর ফেরানো যাবে না।"}
ORIGIN_RETRY = {"hi": "{name} nahi mila, phir se bolenge ya skip karein?",
                "en": "I couldn't find {name}. Say it again, or say skip?", "bn": "{name} খুঁজে পেলাম না। আবার বলবেন, নাকি স্কিপ করবেন?"}
ORIGIN_GIVE_UP = {"hi": "{name} bhi nahi mila, starting city ke bina aage badhte hain.",
                  "en": "I couldn't find {name} either, so we'll go on without a starting city.", "bn": "{name}-ও খুঁজে পেলাম না, কোথা থেকে যাচ্ছেন সেটা ছাড়াই এগোচ্ছি।"}
ORIGIN_CHECK = {"hi": "{name} se? Sahi hai?", "en": "Starting from {name}? Is that right?", "bn": "{name} থেকে যাচ্ছেন? ঠিক আছে?"}
ORIGIN_SAME = {"hi": "{name} se {name} hi jaana hai? Sahi hai?", "en": "Starting from {name} and going to {name}? Is that right?", "bn": "{name} থেকে {name}-এই যাচ্ছেন? ঠিক আছে?"}


def ask_fields(missing: List[str], ask_origin: bool = False, ask_purpose: bool = False, ask_area: bool = False) -> List[str]:
    """What one question asks for: at most MAX_QUESTIONS missing fields (the date pair counts once), in the
    fixed order; the optional origin, then the purpose, then the base area go after them, only into a free slot."""
    fields = [f for f in missing if not (f == "end_date" and "start_date" in missing)][:MAX_QUESTIONS]
    for wanted, name in ((ask_origin, "origin_city"), (ask_purpose, "purpose"), (ask_area, "base_area")):
        if wanted and len(fields) < MAX_QUESTIONS:
            fields.append(name)
    return fields


def question_for(missing: List[str], lang: str, days_known: bool = False, ask_origin: bool = False,
                 ask_purpose: bool = False, ask_area: bool = False) -> str:
    """At most 2 things per question; the date pair counts as one."""
    lang = tkey(lang)
    fields = ask_fields(missing, ask_origin, ask_purpose, ask_area)
    parts = []
    for f in fields:
        if f == "start_date" and days_known:
            parts.append({"hi": "Kab se jaana hai?", "en": "From which date?", "bn": "কোন তারিখ থেকে?"}[lang])
        else:
            parts.append(QUESTIONS[f][lang])
    return " ".join(parts)


def people_words(adults: int, children: int, lang: str) -> str:
    """2, 1 -> "do bade log, ek bachcha" / "2 adults, 1 child"."""
    if lang == "en":
        out = f"{adults} adult{'s' if adults != 1 else ''}"
        return out + (f", {children} child{'ren' if children != 1 else ''}" if children else "")
    if lang == "bn":
        return f"{adults} জন প্রাপ্তবয়স্ক" + (f", {children} জন বাচ্চা" if children else "")
    word = lambda n: HINDI_NUMBERS[n] if 0 <= n < len(HINDI_NUMBERS) else str(n)  # noqa: E731
    out = "ek bada" if adults == 1 else f"{word(adults)} bade log"
    if children:
        out += ", ek bachcha" if children == 1 else f", {word(children)} bachche"
    return out


def purpose_words(draft: TripDraftState, lang: str) -> str:
    """", kaam ke liye, Electronic City ke paas" / ", for work, near Electronic City"; "" when no purpose was given."""
    lang = tkey(lang)
    if not draft.purpose_type:
        return ""
    said = PURPOSE_WORDS.get(draft.purpose_type, {}).get(lang, "")
    # The user's own word ("हैकथन" -> "hackathon ke liye"); the type word only when there is none (or it is long).
    if draft.purpose_type in ("business", "event", "other") and draft.purpose_text             and len(draft.purpose_text) <= _SAY_TEXT_MAX:
        said = OWN_PURPOSE[lang].format(text=draft.purpose_text)
    area = (draft.base_area or {}).get("name")
    if area:
        said += NEAR_AREA[lang].format(area=area)
    return f", {said}" if said else ""


def readback(draft: TripDraftState, lang: str) -> str:
    """Without an origin: the dates only (unchanged). With one: origin se destination, dates, nights, people.
    The purpose and base area are added only when given ("kaam ke liye, Electronic City ke paas")."""
    s, e = parse_date(draft.start_date), parse_date(draft.end_date)
    nights = max((e - s).days, 0)
    why = purpose_words(draft, lang)
    k = tkey(lang)
    parts = {"start": say_date(s, k), "end": say_date(e, k), "nights": nights_words(nights, k), "why": why}
    if draft.origin_city:
        frm, to = (draft.origin_city or {}).get("name", ""), (draft.destination or {}).get("name", "")
        who = people_words(draft.adults or 0, draft.children or 0, k)
        return READBACK_FROM[k].format(frm=frm, to=to, who=who, **parts)
    return READBACK[k].format(**parts)


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
    origin += purpose_words(draft, lang)
    k = tkey(lang)
    return SUMMARY[k].format(dest=dest, origin=origin, start=say_date(s, k), end=say_date(e, k), who=who,
                             budget=draft.budget_inr)


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
        **_purpose_prefill(draft),
    }


def _purpose_prefill(draft: TripDraftState) -> Dict[str, Any]:
    """purposeType / purposeText / baseArea, only when a purpose was given (older prefills stay as they were)."""
    from trip_purpose import is_focused
    if not draft.purpose_type:
        return {}
    focused = is_focused(draft.purpose_type)
    return {"purposeType": draft.purpose_type, "purposeText": draft.purpose_text if focused else None,
            "baseArea": draft.base_area if focused else None}
