"""
Booking conversation, stage 2: QUESTIONS ONLY. Nothing is written to the database and nothing is sent to anyone.

The answers live only in Redis (booking:flow:{user}:{trip}, 2 hours, renewed on every change) and are deleted on
cancel and on finish. The screen (WS booking:* / REST /api/trips/{id}/booking*) and voice (voice/booking_voice.py)
call the SAME functions here, so both read and write the same state.

CODE decides the steps, validates every answer and writes the texts. The current question is always the first one
not answered yet (like the voice trip draft's next_step), so "change X" at the review only clears X and the flow
comes back to the review by itself.

Logs: flags and counts only ([BOOKING FLOW] step=hotel_type answered=true skipped=false). Never names, ages,
phone numbers or any user words.
"""
import json
import logging
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("booking")

FLOW_TTL_SECONDS = 2 * 60 * 60
ANY = "any"                                     # "aap decide karo" / "koi bhi"
SERVICES = ["flight", "train", "hotel"]
SERVICE_QUESTIONS = {
    "flight": ["flight_time", "flight_airline"],
    "train": ["train_class", "train_time", "train_tatkal"],
    "hotel": ["hotel_type", "hotel_rooms", "hotel_elderly"],
}
TIMES = ["morning", "afternoon", "evening", "night"]
TRAIN_CLASSES = ["SL", "3A", "2A", "1A"]
HOTEL_TYPES = ["budget", "3star", "4plus"]
YES_NO = ["yes", "no"]
CHOICES: Dict[str, List[str]] = {          # the allowed values of each tap question ("any" always allowed)
    "flight_time": TIMES, "train_time": TIMES, "train_class": TRAIN_CLASSES, "hotel_type": HOTEL_TYPES,
    "train_tatkal": YES_NO, "hotel_elderly": YES_NO, "flight_airline": ["cheapest"],
}
MAX_ROOMS = 9
NAME_MIN, NAME_MAX = 2, 60
AIRLINE_MAX = 40
AGE_MAX = 110
ADULT_AGE = 18
MAX_TRAVELLERS = 20
CHANGE_PARTS = ["services", "flight", "train", "hotel", "travellers", "phone"]

TEST_NOTE = {"hi": "Test version: kuch bheja nahi jayega", "en": "Test version: nothing will be sent"}
CONSENT = {"hi": "Ye details hamare booking partner ko bheji jayengi.", "en": "These details will be sent to our booking partner."}
DONE = {"hi": "Abhi ye test hai. Kuch bheja nahi gaya.", "en": "This is a test for now. Nothing was sent."}
CANCELLED = {"hi": "Theek hai.", "en": "Okay."}
OFFER = {"hi": "Train, flight ya hotel book karwana hai?", "en": "Want to book a train, flight or hotel?"}

LABELS = {
    "hi": {
        "flight": "Flight", "train": "Train", "hotel": "Hotel",
        "morning": "Subah", "afternoon": "Dopahar", "evening": "Shaam", "night": "Raat",
        "SL": "Sleeper", "3A": "3AC", "2A": "2AC", "1A": "1AC",
        "budget": "Budget", "3star": "3-star", "4plus": "4-star+",
        "yes": "Haan", "no": "Nahi", "cheapest": "Jo sasta mile", ANY: "Aap decide karo",
        "travellers": "Travellers", "phone": "Phone", "services": "Services",
    },
    "en": {
        "flight": "Flight", "train": "Train", "hotel": "Hotel",
        "morning": "Morning", "afternoon": "Afternoon", "evening": "Evening", "night": "Night",
        "SL": "Sleeper", "3A": "3AC", "2A": "2AC", "1A": "1AC",
        "budget": "Budget", "3star": "3-star", "4plus": "4-star+",
        "yes": "Yes", "no": "No", "cheapest": "Cheapest", ANY: "You decide",
        "travellers": "Travellers", "phone": "Phone", "services": "Services",
    },
}

PROMPTS = {
    "hi": {
        "services": "Train, flight ya hotel book karwana hai? Ek ya zyada chuniye.",
        "flight_time": "Flight kis time chahiye? Subah, dopahar, shaam ya raat?",
        "flight_airline": "Koi khaas airline, ya jo sasta mile?",
        "train_class": "Train mein kaunsi class? Sleeper, 3AC, 2AC ya 1AC?",
        "train_time": "Train kis time chahiye? Subah, dopahar, shaam ya raat?",
        "train_tatkal": "Tatkal chalega?",
        "hotel_type": "Hotel kaisa chahiye? Budget, 3-star ya 4-star se upar?",
        "hotel_rooms": "Kitne kamre chahiye? 1 se 9.",
        "hotel_elderly": "Koi bujurg saath hain?",
        "name_adult": "Yatri {n} ka naam?",
        "name_child": "Bachche {n} ka naam?",
        "name_offer": "Pehle yatri {name} hain? Haan boliye, ya naam boliye.",
        "age": "{name} ki umar?",
        "age_child_check": "{name} ki umar {age}? Ye bachche ki jagah hai. Sahi hai?",
        "age_adult_check": "{name} ki umar {age}? Ye bade yatri ki jagah hai. Sahi hai?",
        "phone": "Ek mobile number boliye, 10 digit ka.",
        "phone_ok": "Number: {digits}. Sahi hai?",
        "review": "Sahi hai?",
        "review_screen": "Sab details check kijiye.",
        "change": "Kya badalna hai? Flight, train, hotel, travellers ya phone?",
    },
    "en": {
        "services": "Flight, train or hotel? Pick one or more.",
        "flight_time": "What time for the flight? Morning, afternoon, evening or night?",
        "flight_airline": "Any particular airline, or the cheapest?",
        "train_class": "Which train class? Sleeper, 3AC, 2AC or 1AC?",
        "train_time": "What time for the train? Morning, afternoon, evening or night?",
        "train_tatkal": "Is Tatkal okay?",
        "hotel_type": "What kind of hotel? Budget, 3-star or 4-star and above?",
        "hotel_rooms": "How many rooms? 1 to 9.",
        "hotel_elderly": "Any elderly guests?",
        "name_adult": "Traveller {n}'s name?",
        "name_child": "Child {n}'s name?",
        "name_offer": "Is the first traveller {name}? Say yes, or say the name.",
        "age": "How old is {name}?",
        "age_child_check": "{name} is {age}? This is a child's place. Is that right?",
        "age_adult_check": "{name} is {age}? This is an adult's place. Is that right?",
        "phone": "Please give one mobile number, 10 digits.",
        "phone_ok": "Number: {digits}. Is that right?",
        "review": "Is that right?",
        "review_screen": "Please check the details.",
        "change": "What should I change? Flight, train, hotel, travellers or phone?",
    },
}

ERRORS = {
    "hi": {
        "services_empty": "Kam se kam ek chuniye: flight, train ya hotel.",
        "choice_invalid": "Samajh nahi aaya.",
        "name_invalid": "Naam mein sirf akshar ho sakte hain, 2 se 60 tak.",
        "airline_invalid": "Airline ka naam sirf aksharon mein boliye.",
        "airline_name_needed": "Kaunsi airline?",
        "age_invalid": "Umar 0 se 110 ke beech ek poora number boliye.",
        "rooms_invalid": "Kamre 1 se 9 tak ho sakte hain.",
        "phone_invalid": "Ye number sahi nahi lagta. 10 digit ka mobile number boliye, jo 6, 7, 8 ya 9 se shuru ho.",
        "decide_not_allowed": "Ye aapko batana hoga.",
        "stale": "Ye sawaal badal gaya hai.",
        "trip_past": "Ye trip khatam ho chuki hai.",
        "no_travellers": "Is trip mein koi yatri nahi hai.",
    },
    "en": {
        "services_empty": "Pick at least one: flight, train or hotel.",
        "choice_invalid": "I didn't get that.",
        "name_invalid": "A name can only have letters, 2 to 60 of them.",
        "airline_invalid": "Please say the airline's name in letters only.",
        "airline_name_needed": "Which airline?",
        "age_invalid": "Please give an age as a whole number from 0 to 110.",
        "rooms_invalid": "Rooms can be 1 to 9.",
        "phone_invalid": "That number doesn't look right. Please give a 10-digit mobile number starting with 6, 7, 8 or 9.",
        "decide_not_allowed": "I need this one from you.",
        "stale": "This question has changed.",
        "trip_past": "This trip is already over.",
        "no_travellers": "This trip has no travellers.",
    },
}


class BookingError(ValueError):
    """A refused action (past trip, no travellers). The code is safe to show; the text never quotes the user."""

    def __init__(self, code: str):
        super().__init__(ERRORS["en"].get(code, code))
        self.code = code


@dataclass
class BookingState:
    trip_id: str
    adults: int
    children: int
    services: List[str] = field(default_factory=list)
    answers: Dict[str, Any] = field(default_factory=dict)       # question id -> value ("any" = "aap decide karo")
    travellers: List[Dict[str, Any]] = field(default_factory=list)  # one per person: adults first, then children
    phone: Optional[str] = None                                 # 10 digits
    phone_ok: bool = False                                      # set ONLY after the digit-by-digit read-back got a yes
    age_check: Optional[int] = None                             # an age waiting for "sahi hai?" (adult < 18 / child 18+)
    account_name: Optional[str] = None                          # offered for the first traveller (yes / no)
    account_declined: bool = False
    choosing_change: bool = False                               # "nahi" at the review: which part to change?
    finished: bool = False
    editing_services: bool = False                              # Back / "change services": the choice is shown again
    voice_lang: str = "hi"                                      # the language of the sentence that started the voice flow
    voice_conversation: Optional[str] = None                    # the voice conversation whose last reply asked a question
    voice_asked_at: float = 0.0

    def traveller_count(self) -> int:
        return self.adults + self.children


# ---------------- Redis

def _key(user_id: str, trip_id: str) -> str:
    return f"booking:flow:{user_id}:{trip_id}"


def load(redis_conn, user_id: str, trip_id: str) -> Optional[BookingState]:
    try:
        raw = redis_conn.get(_key(user_id, trip_id))
        if not raw:
            return None
        data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        return BookingState(**{k: v for k, v in data.items() if k in BookingState.__dataclass_fields__})
    except Exception:
        return None


def save(redis_conn, user_id: str, state: BookingState) -> None:
    redis_conn.setex(_key(user_id, state.trip_id), FLOW_TTL_SECONDS, json.dumps(asdict(state)))


def delete(redis_conn, user_id: str, trip_id: str) -> None:
    try:
        redis_conn.delete(_key(user_id, trip_id))
    except Exception:
        pass


def log_event(event: str, state: Optional[BookingState] = None, **flags: Any) -> None:
    """Flags and counts only. Never names, ages, phone numbers or words."""
    parts = [f"event={event}"]
    if state is not None:
        parts.append(f"services={len(state.services)} travellers={state.traveller_count()}")
    parts += [f"{k}={str(v).lower() if isinstance(v, bool) else v}" for k, v in flags.items()]
    logger.info("[BOOKING FLOW] %s", " ".join(parts))


# ---------------- validation (shared by screen and voice)

def _letters_only(text: str) -> bool:
    return all(unicodedata.category(ch)[0] in "LM" or ch == " " for ch in text)


def clean_name(raw: Any, max_chars: int = NAME_MAX) -> Optional[str]:
    """Letters (any script, with their vowel marks) and spaces only, 2..max_chars characters."""
    if not isinstance(raw, str):
        return None
    text = " ".join(unicodedata.normalize("NFC", raw).split())
    if not (NAME_MIN <= len(text) <= max_chars) or not _letters_only(text):
        return None
    if sum(1 for ch in text if unicodedata.category(ch)[0] == "L") < 2:
        return None
    return text


def _ascii_digits(text: str) -> str:
    out = []
    for ch in text:
        if ch.isdigit():
            try:
                out.append(str(unicodedata.digit(ch)))
            except (TypeError, ValueError):
                return ""
    return "".join(out)


def normalize_phone(raw: Any) -> Optional[str]:
    """Indian mobile: 10 digits starting 6-9, optional +91 / 91 / 0 prefix. Anything but digits, spaces, '+', '-'
    and brackets is refused (letters are never dropped silently)."""
    if isinstance(raw, int):
        raw = str(raw)
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if any(not (ch.isdigit() or ch in " +-()") for ch in text):
        return None
    digits = _ascii_digits(text)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] not in "6789":
        return None
    return digits


def parse_age(raw: Any) -> Optional[int]:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        n = raw
    elif isinstance(raw, str) and raw.strip() and all(ch.isdigit() for ch in raw.strip()):
        n = int(_ascii_digits(raw.strip()))
    else:
        return None
    return n if 0 <= n <= AGE_MAX else None


def spaced_digits(phone: str) -> str:
    """Digit by digit, in two groups: "9 8 7 6 5, 4 3 2 1 0"."""
    return f"{' '.join(phone[:5])}, {' '.join(phone[5:])}"


# ---------------- the questions (order decides the flow)

def question_ids(s: BookingState) -> List[str]:
    q = ["services"]
    for svc in SERVICES:
        if svc in s.services:
            q += SERVICE_QUESTIONS[svc]
    for i in range(s.traveller_count()):
        q += [f"t{i}_name", f"t{i}_age"]
    return q + ["phone", "phone_ok", "review"]


def _traveller(qid: str) -> Optional[Tuple[int, str]]:
    m = re.fullmatch(r"t(\d+)_(name|age)", qid)
    return (int(m.group(1)), m.group(2)) if m else None


def is_answered(s: BookingState, qid: str) -> bool:
    if qid == "services":
        return bool(s.services)
    t = _traveller(qid)
    if t:
        i, part = t
        return i < len(s.travellers) and s.travellers[i].get(part) is not None
    if qid == "phone":
        return s.phone is not None
    if qid == "phone_ok":
        return s.phone_ok
    if qid == "review":
        return s.finished
    return qid in s.answers


def base_question(s: BookingState) -> str:
    if s.editing_services:
        return "services"
    for qid in question_ids(s):
        if not is_answered(s, qid):
            return qid
    return "review"


def current_question(s: BookingState) -> str:
    """The question on screen / asked by voice now, including the small yes/no sub-steps."""
    qid = base_question(s)
    if s.age_check is not None and (_traveller(qid) or (0, ""))[1] == "age":
        return qid + "_confirm"
    if qid == "review" and s.choosing_change:
        return "change"
    return qid


def offers_account_name(s: BookingState, qid: str) -> bool:
    return qid == "t0_name" and bool(s.account_name) and not s.account_declined and s.adults > 0


def _is_child(s: BookingState, i: int) -> bool:
    return i >= s.adults


def _person_label(s: BookingState, i: int, lang: str) -> str:
    name = (s.travellers[i].get("name") if i < len(s.travellers) else None)
    if name:
        return name
    if _is_child(s, i):
        return ("Bachcha {n}" if lang == "hi" else "Child {n}").format(n=i - s.adults + 1)
    return ("Yatri {n}" if lang == "hi" else "Traveller {n}").format(n=i + 1)


# ---------------- applying answers

@dataclass
class Outcome:
    ok: bool
    error: Optional[str] = None      # an ERRORS code
    finished: bool = False


def _drop_service_answers(s: BookingState, svc: str) -> None:
    for qid in SERVICE_QUESTIONS[svc]:
        s.answers.pop(qid, None)


def _reset_travellers(s: BookingState) -> None:
    s.travellers = [{"name": None, "age": None} for _ in range(s.traveller_count())]
    s.age_check = None
    s.account_declined = False


def change_part(s: BookingState, part: str) -> bool:
    """Review: clear one part only; the flow asks it again and comes back to the review by itself."""
    if part not in CHANGE_PARTS:
        return False
    s.choosing_change = False
    if part == "services":
        s.editing_services = True
    elif part in SERVICE_QUESTIONS:
        if part not in s.services:
            s.services = [x for x in SERVICES if x in s.services or x == part]
        _drop_service_answers(s, part)
    elif part == "travellers":
        _reset_travellers(s)
    elif part == "phone":
        s.phone, s.phone_ok = None, False
    return True


def apply_answer(s: BookingState, question: str, value: Any) -> Outcome:
    """The ONE place answers are checked. `question` must be the current question (a stale screen is refused)."""
    qid = current_question(s)
    if question != qid:
        return Outcome(False, "stale")
    t = _traveller(qid)

    if qid == "services":
        chosen = value if isinstance(value, list) else [value]
        chosen = [x for x in SERVICES if x in chosen]
        if not chosen:
            return Outcome(False, "services_empty")
        s.services = chosen
        s.editing_services = False
        for svc in SERVICES:
            if svc not in chosen:
                _drop_service_answers(s, svc)
        return Outcome(True)

    if qid == "flight_airline":
        if value in ("cheapest", ANY):
            s.answers[qid] = value
            return Outcome(True)
        name = clean_name(value, AIRLINE_MAX)
        if not name:
            return Outcome(False, "airline_invalid")
        s.answers[qid] = name
        return Outcome(True)

    if qid in CHOICES:
        if value != ANY and value not in CHOICES[qid]:
            return Outcome(False, "choice_invalid")
        s.answers[qid] = value
        return Outcome(True)

    if qid == "hotel_rooms":
        if value == ANY:
            s.answers[qid] = ANY
            return Outcome(True)
        n = parse_age(value)
        if n is None or not 1 <= n <= MAX_ROOMS:
            return Outcome(False, "rooms_invalid")
        s.answers[qid] = n
        return Outcome(True)

    if t and t[1] == "name":
        i = t[0]
        if value == ANY:
            return Outcome(False, "decide_not_allowed")
        if offers_account_name(s, qid) and value in ("yes", "no"):
            if value == "yes":
                s.travellers[i]["name"] = s.account_name
            else:
                s.account_declined = True
            return Outcome(True)
        name = clean_name(value)
        if not name:
            return Outcome(False, "name_invalid")
        s.travellers[i]["name"] = name
        return Outcome(True)

    if t and t[1] == "age":
        i = t[0]
        if value == ANY:
            return Outcome(False, "decide_not_allowed")
        age = parse_age(value)
        if age is None:
            return Outcome(False, "age_invalid")
        child = _is_child(s, i)
        if (child and age >= ADULT_AGE) or (not child and age < ADULT_AGE):
            s.age_check = age                       # ask once: "sahi hai?"
            return Outcome(True)
        s.travellers[i]["age"] = age
        return Outcome(True)

    if qid.endswith("_age_confirm"):
        i = (_traveller(qid[: -len("_confirm")]) or (0, ""))[0]
        if value == "yes":
            s.travellers[i]["age"] = s.age_check
            s.age_check = None
            return Outcome(True)
        if value == "no":
            s.age_check = None
            return Outcome(True)
        return Outcome(False, "choice_invalid")

    if qid == "phone":
        if value == ANY:
            return Outcome(False, "decide_not_allowed")
        phone = normalize_phone(value)
        if not phone:
            return Outcome(False, "phone_invalid")
        s.phone, s.phone_ok = phone, False
        return Outcome(True)

    if qid == "phone_ok":
        if value == "yes":
            s.phone_ok = True
            return Outcome(True)
        if value == "no":
            s.phone = None
            return Outcome(True)
        return Outcome(False, "choice_invalid")

    if qid == "review":
        if value == "yes":
            s.finished = True
            return Outcome(True, finished=True)
        if value == "no":
            s.choosing_change = True
            return Outcome(True)
        if isinstance(value, str) and value.startswith("change:") and change_part(s, value[len("change:"):]):
            return Outcome(True)
        return Outcome(False, "choice_invalid")

    if qid == "change":
        part = value[len("change:"):] if isinstance(value, str) and value.startswith("change:") else value
        if isinstance(part, str) and change_part(s, part):
            return Outcome(True)
        return Outcome(False, "choice_invalid")

    return Outcome(False, "choice_invalid")


def go_back(s: BookingState) -> bool:
    """Back button: the previous question is asked again (its answer is cleared)."""
    if s.age_check is not None:
        s.age_check = None
        return True
    if s.choosing_change:
        s.choosing_change = False
        return True
    if s.editing_services:
        return False
    order = question_ids(s)
    k = order.index(base_question(s))
    if k == 0:
        return False
    prev = order[k - 1]
    t = _traveller(prev)
    if prev == "services":
        s.editing_services = True               # the earlier choice stays selected on the screen
    elif t:
        s.travellers[t[0]][t[1]] = None
        if t == (0, "name"):
            s.account_declined = False
    elif prev == "phone":
        s.phone, s.phone_ok = None, False
    elif prev == "phone_ok":
        s.phone_ok = False
    else:
        s.answers.pop(prev, None)
    return True


# ---------------- texts and the screen's view

def _value_label(value: Any, lang: str) -> str:
    if isinstance(value, int):
        return str(value)
    return LABELS[lang].get(value, str(value))


def summary_lines(s: BookingState, lang: str) -> List[Dict[str, str]]:
    L = LABELS[lang]
    hi = lang == "hi"
    lines: List[Dict[str, str]] = []
    a = s.answers
    if "flight" in s.services:
        airline = a.get("flight_airline")
        lines.append({"part": "flight", "label": L["flight"], "text": ", ".join([
            f"{'Time' if not hi else 'Samay'}: {_value_label(a.get('flight_time'), lang)}",
            f"Airline: {_value_label(airline, lang)}"])})
    if "train" in s.services:
        lines.append({"part": "train", "label": L["train"], "text": ", ".join([
            f"Class: {_value_label(a.get('train_class'), lang)}",
            f"{'Time' if not hi else 'Samay'}: {_value_label(a.get('train_time'), lang)}",
            f"Tatkal: {_value_label(a.get('train_tatkal'), lang)}"])})
    if "hotel" in s.services:
        lines.append({"part": "hotel", "label": L["hotel"], "text": ", ".join([
            f"{'Type' if not hi else 'Prakaar'}: {_value_label(a.get('hotel_type'), lang)}",
            f"{'Rooms' if not hi else 'Kamre'}: {_value_label(a.get('hotel_rooms'), lang)}",
            f"{'Elderly' if not hi else 'Bujurg'}: {_value_label(a.get('hotel_elderly'), lang)}"])})
    people = [f"{t.get('name')} ({t.get('age')})" for t in s.travellers]
    lines.append({"part": "travellers", "label": L["travellers"], "text": ", ".join(people)})
    lines.append({"part": "phone", "label": L["phone"], "text": f"{s.phone[:5]} {s.phone[5:]}" if s.phone else "—"})
    return lines


def spoken_review(s: BookingState, lang: str) -> str:
    """Short, for voice: services + choices, number of travellers, the phone in two groups."""
    hi = lang == "hi"
    parts = []
    for line in summary_lines(s, lang):
        if line["part"] in SERVICES:
            parts.append(f"{line['label']}: {line['text']}.")
    n = s.traveller_count()
    parts.append(f"{n} yatri." if hi else f"{n} traveller{'s' if n != 1 else ''}.")
    if s.phone:
        parts.append(f"Phone {s.phone[:5]} {s.phone[5:]}.")
    return " ".join(parts)


def prompt_for(s: BookingState, qid: str, lang: str, spoken: bool = False) -> str:
    P = PROMPTS[lang]
    t = _traveller(qid)
    if t and t[1] == "name":
        i = t[0]
        if offers_account_name(s, qid):
            return P["name_offer"].format(name=s.account_name)
        if _is_child(s, i):
            return P["name_child"].format(n=i - s.adults + 1)
        return P["name_adult"].format(n=i + 1)
    if t and t[1] == "age":
        return P["age"].format(name=_person_label(s, t[0], lang))
    if qid.endswith("_age_confirm"):
        i = (_traveller(qid[: -len("_confirm")]) or (0, ""))[0]
        key = "age_child_check" if _is_child(s, i) else "age_adult_check"
        return P[key].format(name=_person_label(s, i, lang), age=s.age_check)
    if qid == "phone_ok":
        return P["phone_ok"].format(digits=spaced_digits(s.phone or ""))
    if qid == "review":
        if not spoken:
            return P["review_screen"]             # the screen shows the summary and the consent line under it
        return f"{spoken_review(s, lang)} {CONSENT[lang]} {P['review']}"
    return P[qid]


def _choices(s: BookingState, qid: str, lang: str) -> List[Dict[str, str]]:
    L = LABELS[lang]
    if qid == "services":
        return [{"value": x, "label": L[x]} for x in SERVICES]
    if qid == "flight_airline":
        return [{"value": "cheapest", "label": L["cheapest"]}, {"value": ANY, "label": L[ANY]}]
    if qid in CHOICES:
        return [{"value": x, "label": L[x]} for x in CHOICES[qid]] + [{"value": ANY, "label": L[ANY]}]
    if qid == "hotel_rooms":
        return [{"value": str(n), "label": str(n)} for n in range(1, MAX_ROOMS + 1)] + [{"value": ANY, "label": L[ANY]}]
    if qid.endswith("_age_confirm") or qid == "phone_ok":
        return [{"value": "yes", "label": L["yes"]}, {"value": "no", "label": L["no"]}]
    if offers_account_name(s, qid):
        return [{"value": "yes", "label": (f"Haan, {s.account_name}" if lang == "hi" else f"Yes, {s.account_name}")}]
    if qid == "change":
        return [{"value": f"change:{p}", "label": L[p]} for p in CHANGE_PARTS]
    return []


def _kind(qid: str) -> str:
    t = _traveller(qid)
    if qid == "services":
        return "services"
    if t:
        return "name" if t[1] == "name" else "age"
    if qid in ("phone", "review", "change"):
        return qid
    if qid.endswith("_age_confirm") or qid == "phone_ok":
        return "yesno"
    return "choice"


def _section(s: BookingState, qid: str) -> Tuple[int, int]:
    sections = ["services"] + [x for x in SERVICES if x in s.services] + ["travellers", "phone", "review"]
    if qid == "services":
        name = "services"
    elif _traveller(qid) or qid.endswith("_age_confirm"):
        name = "travellers"
    elif qid in ("phone", "phone_ok"):
        name = "phone"
    elif qid in ("review", "change"):
        name = "review"
    else:
        name = next((svc for svc, qs in SERVICE_QUESTIONS.items() if qid in qs), "services")
    return sections.index(name) + 1, len(sections)


def view(s: BookingState, lang: str = "hi", error: Optional[str] = None) -> Dict[str, Any]:
    """Everything the screen needs for the current step. No prices, no availability, no suggestions."""
    qid = current_question(s)
    step, total = _section(s, qid)
    t = _traveller(qid) or _traveller(qid[: -len("_confirm")] if qid.endswith("_confirm") else "")
    out: Dict[str, Any] = {
        "active": True,
        "tripId": s.trip_id,
        "question": qid,
        "kind": _kind(qid),
        "prompt": prompt_for(s, qid, lang),
        "choices": _choices(s, qid, lang),
        "allowText": qid in ("flight_airline",) or _kind(qid) in ("name", "age", "phone"),
        "selected": list(s.services) if qid == "services" else [],
        "progress": {"step": step, "total": total, "label": f"{step} of {total}"},
        "canBack": qid != "services" or s.choosing_change,
        "testNote": TEST_NOTE[lang],
        "error": ERRORS[lang].get(error) if error else None,
        "errorCode": error,
    }
    if t:
        out["traveller"] = {"index": t[0] + 1, "isChild": _is_child(s, t[0]), "total": s.traveller_count()}
    if qid in ("review", "change"):
        out["summary"] = summary_lines(s, lang)
        out["consent"] = CONSENT[lang]
    return out


# ---------------- entry points (screen WS/REST and voice)

def _trip_is_past(trip) -> bool:
    from trip_lifecycle import today_ist
    try:
        return date.fromisoformat(str(trip.end_date)[:10]) < today_ist()
    except ValueError:
        return False


def _counts(trip) -> Tuple[int, int]:
    travellers = trip.travelers or []
    adults = sum(1 for t in travellers if isinstance(t, dict) and t.get("type") != "CHILD")
    children = sum(1 for t in travellers if isinstance(t, dict) and t.get("type") == "CHILD")
    return adults, children


def _account_name(db, user_id: str) -> Optional[str]:
    try:
        from models_db import UserProfileModel
        p = db.query(UserProfileModel).filter(UserProfileModel.user_id == user_id).first()
        return clean_name(f"{p.first_name or ''} {p.last_name or ''}".strip()) if p else None
    except Exception:
        return None


def start(redis_conn, db, user_id: str, trip, services: Optional[List[str]] = None) -> BookingState:
    """Resume the flow for this trip, or start a new one. `trip` is already owner-checked by the caller."""
    s = load(redis_conn, user_id, trip.id)
    if s is not None:
        log_event("resume", s, step=current_question(s))
        return s
    if trip.status == "COMPLETED" or _trip_is_past(trip):
        raise BookingError("trip_past")
    adults, children = _counts(trip)
    if adults + children == 0:
        raise BookingError("no_travellers")
    adults, children = min(adults, MAX_TRAVELLERS), min(children, MAX_TRAVELLERS - min(adults, MAX_TRAVELLERS))
    s = BookingState(trip_id=trip.id, adults=adults, children=children, account_name=_account_name(db, user_id))
    _reset_travellers(s)
    chosen = [x for x in SERVICES if x in (services or [])]
    if chosen:
        s.services = chosen
    save(redis_conn, user_id, s)
    log_event("start", s, services_given=bool(chosen), name_offered=bool(s.account_name))
    return s


def answer(redis_conn, user_id: str, trip_id: str, question: str, value: Any) -> Tuple[Optional[BookingState], Outcome]:
    s = load(redis_conn, user_id, trip_id)
    if s is None:
        return None, Outcome(False, "expired")
    qid = current_question(s)
    out = apply_answer(s, str(question or ""), value)
    log_event("answer", s, step=re.sub(r"^t\d+_", "traveller_", qid), answered=out.ok,
              skipped=bool(out.ok and value == ANY), error=out.error or "none")
    if out.finished:
        delete(redis_conn, user_id, trip_id)
        log_event("finish", s, sent=False)
    else:
        save(redis_conn, user_id, s)
    return s, out


def back(redis_conn, user_id: str, trip_id: str) -> Optional[BookingState]:
    s = load(redis_conn, user_id, trip_id)
    if s is None:
        return None
    moved = go_back(s)
    save(redis_conn, user_id, s)
    log_event("back", s, moved=moved)
    return s


def cancel(redis_conn, user_id: str, trip_id: str) -> bool:
    s = load(redis_conn, user_id, trip_id)
    delete(redis_conn, user_id, trip_id)
    log_event("cancel", s, had_flow=s is not None)
    return s is not None


# ---------------- the WS / REST response shape

def response(s: Optional[BookingState], out: Optional[Outcome] = None, lang: str = "hi") -> Dict[str, Any]:
    if out is not None and out.finished:
        return {"active": False, "finished": True, "message": DONE[lang], "testNote": TEST_NOTE[lang]}
    if s is None:
        return {"active": False, "expired": bool(out and out.error == "expired"), "offer": OFFER[lang],
                "testNote": TEST_NOTE[lang]}
    return view(s, lang, out.error if out is not None and not out.ok else None)


SCREEN_ACTIONS = {"booking:get", "booking:start", "booking:answer", "booking:back", "booking:cancel"}


def screen_action(redis_conn, db, user_id: str, trip, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """WS booking:* and the REST routes. `trip` is the owner-checked trip; the key is always the session user's."""
    if action == "booking:get":
        return response(load(redis_conn, user_id, trip.id))
    if action == "booking:start":
        services = data.get("services") if isinstance(data.get("services"), list) else None
        return response(start(redis_conn, db, user_id, trip, services))
    if action == "booking:answer":
        s, out = answer(redis_conn, user_id, trip.id, str(data.get("question") or "")[:40], _screen_value(data.get("value")))
        return response(s, out)
    if action == "booking:back":
        return response(back(redis_conn, user_id, trip.id))
    if action == "booking:cancel":
        cancel(redis_conn, user_id, trip.id)
        return {"active": False, "cancelled": True, "message": CANCELLED["hi"], "offer": OFFER["hi"]}
    raise ValueError("Unknown booking action")


def _screen_value(raw: Any) -> Any:
    """Only short strings, small ints or a short list of strings come from the screen."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        return raw[:80]
    if isinstance(raw, list):
        return [x[:20] for x in raw[:5] if isinstance(x, str)]
    return None
