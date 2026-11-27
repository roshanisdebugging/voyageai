"""
Booking stage 2 by voice: the same steps and the same Redis state as the screen (booking_flow.py).

run_agent calls handle() AFTER its yes/no and origin branches. It answers only when
  - the user asks to book ("book karwana hai", "hotel book karo", "होटल बुक करो", "book a train"), or
  - this voice conversation's last reply asked a booking question (within ANSWER_WINDOW_S).
A flow left half-way is resumed by asking to book again. Without an open trip: "Pehle trip kholiye".

CODE turns the words into an answer (choices, numbers, yes/no, phone digits in Hindi / Hinglish / English) and
booking_flow checks it. The model is called only for a name / age / phone that code could not read, and only to
EXTRACT what was said (it never decides a step or writes a reply); its output is checked by the same code.
Booking turns are not kept in the voice memory (names and numbers stay only in the booking state).
Logs: flags only.
"""
import logging
import re
import time
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

import booking_flow as BF
from voice.text_utils import canon, words as tu_words

logger = logging.getLogger("voice")

ANSWER_WINDOW_S = 10 * 60
NO_TRIP = {"hi": "Pehle trip kholiye.", "en": "Please open a trip first."}
UNCLEAR = {"hi": "Samajh nahi aaya.", "en": "I didn't get that."}
RESUMED = {"hi": "Booking wahin se:", "en": "Continuing the booking:"}
REFRESH = {"type": "refresh", "what": "booking"}


def _set(*items: str) -> set:
    return {w if w.isdigit() else canon(w) for w in items}


# ---------------- tokens: words in canonical form, digit runs as ASCII digits ("3ac" -> "3", "ac")

def tokens(text: str) -> List[str]:
    out: List[str] = []
    run, kind = [], None
    for ch in unicodedata.normalize("NFC", text or "").lower():
        k = "d" if ch.isdigit() else ("w" if unicodedata.category(ch)[0] in "LM" else None)
        if k != kind and run:
            out.append("".join(run))
            run = []
        kind = k
        if k == "d":
            try:
                run.append(str(unicodedata.digit(ch)))
            except (TypeError, ValueError):
                kind = None
        elif k == "w":
            run.append(ch)
    if run:
        out.append("".join(run))
    result: List[str] = []
    for t in out:
        result += [t] if t.isdigit() else tu_words(t)
    return result


def _has_phrase(toks: List[str], phrase: Tuple[str, ...]) -> bool:
    n = len(phrase)
    return any(tuple(toks[i:i + n]) == phrase for i in range(len(toks) - n + 1))


def _phrases(*items: str) -> List[Tuple[str, ...]]:
    return [tuple(tu_words(p)) for p in items]


# ---------------- starting the flow

_BOOK = _set("book", "booking", "bookings", "reserve", "बुक", "बुकिंग", "बूक")
_SERVICE_WORDS = {
    "flight": _set("flight", "flights", "plane", "aeroplane", "airplane", "hawai", "hawaai", "jahaz", "jahaj",
                   "फ्लाइट", "फ्लाईट", "हवाई", "जहाज", "विमान"),
    "train": _set("train", "trains", "rail", "railway", "ट्रेन", "रेल", "रेलगाड़ी", "ट्रैन"),
    "hotel": _set("hotel", "hotels", "hotal", "होटल", "होटेल", "होटलों"),
}
_ALL_SERVICES = _set("teeno", "teenon", "tino", "sab", "sabhi", "all", "everything", "तीनों", "सब", "सभी")


def services_in(toks: List[str]) -> List[str]:
    if set(toks) & _ALL_SERVICES:
        return list(BF.SERVICES)
    return [svc for svc in BF.SERVICES if set(toks) & _SERVICE_WORDS[svc]]


# Bookings this flow does NOT cover keep going to the model as before (cab -> rides hand-off, a restaurant table).
_NOT_OURS = _set("cab", "cabs", "taxi", "auto", "uber", "ola", "ride", "rides", "rapido", "table", "restaurant",
                 "कैब", "टैक्सी", "ऑटो", "उबर", "ओला", "टेबल", "रेस्टोरेंट")


def is_trigger(text: str) -> bool:
    """"book karwana hai", "hotel book karo", "मुझे ट्रेन बुक करनी है", "book a flight", "booking jaari rakho"."""
    toks = tokens(text)
    return bool(set(toks) & _BOOK) and not set(toks) & _NOT_OURS and len(toks) <= 12


# ---------------- leaving the flow

_CANCEL_PHRASES = _phrases("abhi nahi", "abhi nahin", "abhi na", "अभी नहीं", "rehne do", "rahne do", "रहने दो",
                           "booking cancel", "बुकिंग कैंसल", "band karo", "बंद करो", "not now", "stop booking")
_CANCEL_WORDS = _set("cancel", "कैंसल", "chhodo", "chodo", "chhod", "छोड़ो", "छोडो", "छोड़", "रद्द")


def is_cancel(text: str) -> bool:
    toks = tokens(text)
    if not toks or len(toks) > 6:
        return False
    return bool(set(toks) & _CANCEL_WORDS) or any(_has_phrase(toks, p) for p in _CANCEL_PHRASES)


# ---------------- small answers

_DECIDE_PHRASES = _phrases("aap decide", "aap hi decide", "you decide", "aap dekh", "aap dekh lo", "aap tay", "aap tai",
                           "koi bhi", "kuch bhi", "jo theek", "jo thik", "jo sahi", "aap batao", "aap bataiye",
                           "आप तय", "आप डिसाइड", "आप देख", "कोई भी", "कुछ भी", "जो ठीक", "आप बताइए", "your choice")
_DECIDE_WORDS = _set("any", "anything", "anyone", "decide", "डिसाइड", "whatever")


def is_decide(toks: List[str]) -> bool:
    return bool(set(toks) & _DECIDE_WORDS) or any(_has_phrase(toks, p) for p in _DECIDE_PHRASES)


_YES_EXTRA = _set("chalega", "chalegi", "chalenge", "चलेगा", "चलेगी", "hain", "हैं", "ha", "ji", "जी", "haan", "हां",
                  "haanji", "हांजी", "yes", "ok", "okay", "ओके", "sure", "bilkul", "बिल्कुल", "zaroor", "जरूर", "theek",
                  "thik", "ठीक", "sahi", "सही", "yeah", "yep")
_NO_WORDS = _set("nahi", "nahin", "nai", "na", "no", "nope", "नहीं", "ना", "नो", "mat", "मत", "galat", "गलत", "wrong")


def yes_no(text: str) -> Optional[str]:
    from voice.agent import yes_or_no
    said = yes_or_no(text)
    if said:
        return said
    toks = tokens(text)
    if not toks or len(toks) > 6:
        return None
    if set(toks) & _NO_WORDS:
        return "no"
    if set(toks) & _YES_EXTRA:
        return "yes"
    return None


# ---------------- numbers: digits, English words, Hindi in Devanagari and the common Roman spellings

_DEV_NUMBERS = ("शून्य एक दो तीन चार पांच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस बीस "
                "इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस "
                "छत्तीस सैंतीस अड़तीस उनतालीस चालीस इकतालीस बयालीस तैंतालीस चवालीस पैंतालीस छियालीस सैंतालीस "
                "अड़तालीस उनचास पचास इक्यावन बावन तिरेपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ इकसठ बासठ "
                "तिरसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर "
                "छिहत्तर सतहत्तर अठहत्तर उन्यासी अस्सी इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी "
                "नवासी नब्बे इक्यानवे बानवे तिरानवे चौरानवे पचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे सौ").split()
NUMBER_WORDS: Dict[str, int] = {canon(w): i for i, w in enumerate(_DEV_NUMBERS)}
NUMBER_WORDS.update({canon(w): n for w, n in (("छः", 6), ("छे", 6), ("जीरो", 0), ("ज़ीरो", 0), ("पाँच", 5))})
_ROMAN = ("shunya ek do teen chaar paanch chhe saat aath nau das gyaarah baarah terah chaudah pandrah solah satrah "
          "athaarah unnees bees ikkees baaees teyees chaubees pachchees chhabbees sattaees atthaees unatees tees").split()
NUMBER_WORDS.update({w: i for i, w in enumerate(_ROMAN)})
NUMBER_WORDS.update({"zero": 0, "sifar": 0, "shoonya": 0, "tin": 3, "char": 4, "panch": 5, "chah": 6, "chhah": 6,
                     "che": 6, "chheh": 6, "sat": 7, "ath": 8, "gyarah": 11, "barah": 12, "pandrah": 15, "solha": 16,
                     "atharah": 18, "unnis": 19, "bis": 20, "ikkis": 21, "bais": 22, "teis": 23, "chobis": 24,
                     "pachis": 25, "pacchis": 25, "chabbis": 26, "sattais": 27, "athais": 28, "untis": 29, "tis": 30,
                     "chalis": 40, "chaalees": 40, "chaalis": 40, "pachas": 50, "pachaas": 50, "sattar": 70,
                     "assi": 80, "assee": 80, "nabbe": 90, "sau": 100})
_EN_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                        "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_EN_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


def numbers_in(toks: List[str]) -> List[int]:
    """Every number said, in order: "34", "thirty four", "चौंतीस", "chautees" (if known)."""
    out: List[int] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.isdigit():
            out.append(int(t))
        elif t in _EN_TENS:
            n = _EN_TENS[t]
            if i + 1 < len(toks) and toks[i + 1] in _EN_UNITS and 0 < _EN_UNITS[toks[i + 1]] < 10:
                n += _EN_UNITS[toks[i + 1]]
                i += 1
            out.append(n)
        elif t == "hundred" or t in _EN_UNITS:
            out.append(100 if t == "hundred" else _EN_UNITS[t])
        elif t in NUMBER_WORDS:
            out.append(NUMBER_WORDS[t])
        i += 1
    return out


_AGE_UNITS = _set("saal", "sal", "saal", "baras", "varsh", "years", "year", "yrs", "साल", "वर्ष", "बरस")


# ---------------- phone digits ("nau aath saat...", "double five", "नौ आठ", "98765 43210", "plus 91 ...")

_DIGIT_WORDS: Dict[str, str] = {}
for _w, _d in list(NUMBER_WORDS.items()):
    if _d < 10:
        _DIGIT_WORDS[_w] = str(_d)
for _w, _d in _EN_UNITS.items():
    if _d < 10:
        _DIGIT_WORDS[_w] = str(_d)
_DIGIT_WORDS["oh"] = "0"
_REPEAT = {"double": 2, "triple": 3, "डबल": 2, "ट्रिपल": 3, "dabal": 2}
_PHONE_FILLER = _set("mera", "meri", "number", "no", "phone", "mobile", "hai", "he", "is", "my", "plus", "ka", "ki",
                     "मेरा", "नंबर", "नम्बर", "फोन", "फ़ोन", "मोबाइल", "है", "प्लस", "का", "की", "it's", "its",
                     "and", "aur", "और")


def phone_digits(text: str) -> Optional[str]:
    """The digits said, in order, or None when other words are mixed in (then the model may extract)."""
    toks = tokens(text)
    out: List[str] = []
    repeat = 1
    for t in toks:
        if t in _REPEAT:
            repeat = _REPEAT[t]
            continue
        if t.isdigit():
            out.append(t[0] * repeat + t[1:] if repeat > 1 else t)
        elif t in _DIGIT_WORDS:
            out.append(_DIGIT_WORDS[t] * repeat)
        elif t in NUMBER_WORDS and 10 <= NUMBER_WORDS[t] <= 99:
            out.append(str(NUMBER_WORDS[t]))             # "अट्ठानवे" said as a pair
        elif t in _EN_TENS or t in _EN_UNITS:
            out.append(str(_EN_TENS.get(t, _EN_UNITS.get(t))))
        elif t in _PHONE_FILLER or t in _NO_WORDS or t in _YES_EXTRA:
            pass                                          # "nahi, 9 1 2 ..." at the read-back
        else:
            return None
        repeat = 1
    digits = "".join(out)
    return digits or None


# ---------------- names ("Mera naam Rahul Sharma hai", "Rahul, 34 saal", "राहुल शर्मा")

_NAME_FILLER = _set(
    "mera", "meri", "mere", "naam", "name", "is", "hai", "hain", "he", "my", "its", "it's", "i", "am", "main", "mai",
    "ka", "ki", "ke", "unka", "unki", "uska", "uski", "inka", "inki", "iska", "iski", "aur", "wo", "woh", "voh", "ye",
    "yeh", "umar", "umr", "age", "old", "ji", "sir", "pehla", "pehle", "dusra", "yatri", "traveller", "traveler",
    "bachche", "bachcha", "bachchi", "beta", "beti", "child", "the", "of", "and", "aged", "naam", "called",
    "मेरा", "मेरी", "नाम", "है", "हैं", "उनका", "उनकी", "उसका", "उसकी", "इनका", "इनकी", "और", "वो", "वह", "यह", "ये", "उम्र",
    "का", "की", "के", "जी", "मैं", "पहले", "पहला", "यात्री", "बच्चे", "बच्चा", "बच्ची", "बेटा", "बेटी")


def name_and_age(text: str) -> Tuple[Optional[str], Optional[int], bool]:
    """(name, age, unsure). Code only: filler words and numbers are taken out; `unsure` = a word next to "saal"
    that we can't read as a number (it would end up inside the name)."""
    toks = tokens(text)
    ages = numbers_in(toks)
    name_words = [t for t in toks if not t.isdigit() and t not in NUMBER_WORDS and t not in _EN_UNITS
                  and t not in _EN_TENS and t not in _NAME_FILLER and t not in _AGE_UNITS]
    unsure = bool(set(toks) & _AGE_UNITS) and not ages
    name = " ".join(w.capitalize() if w.isascii() else w for w in name_words) or None
    return name, (ages[0] if len(ages) == 1 else None), unsure or len(ages) > 1


# ---------------- choices

_TIMES = {"morning": _set("subah", "subha", "suba", "subeh", "morning", "savere", "sawere", "savera", "सुबह", "सवेरे",
                          "सवेरा", "सुबे"),
          "afternoon": _set("dopahar", "dopehar", "dupahar", "dopaher", "afternoon", "noon", "din", "दोपहर", "दुपहर",
                            "दिन"),
          "evening": _set("shaam", "sham", "evening", "sandhya", "शाम", "संध्या"),
          "night": _set("raat", "rat", "night", "रात", "रात्रि")}
_SLEEPER = _set("sleeper", "sleepar", "slipar", "sliper", "sl", "स्लीपर", "स्लिपर")
_AC = _set("ac", "a", "tier", "एसी", "ए", "टियर", "टायर", "class", "क्लास")
_CLASS_NUM = {**{w: "1A" for w in _set("1", "first", "ek", "pehla", "pehli", "फर्स्ट", "एक", "one", "वन", "पहला")},
              **{w: "2A" for w in _set("2", "second", "do", "doosra", "dusra", "सेकंड", "सेकेंड", "दो", "two", "टू", "दूसरा")},
              **{w: "3A" for w in _set("3", "third", "teen", "tisra", "teesra", "थर्ड", "तीन", "three", "थ्री", "तीसरा")}}
_BUDGET = _set("budget", "sasta", "sasti", "saste", "cheap", "cheapest", "economy", "बजट", "सस्ता", "सस्ती")
_STAR = _set("star", "stars", "sitara", "sitare", "स्टार", "सितारा")
_LUXURY = _set("luxury", "premium", "lakjari", "लक्जरी", "लग्जरी")
_CHEAPEST = _BUDGET
_AIRLINE_FILLER = _set("koi", "khaas", "khas", "airline", "airlines", "se", "chahiye", "chaiye", "hai", "mujhe", "wali",
                       "wala", "flight", "ki", "ka", "me", "mein", "prefer", "please", "particular", "कोई", "खास",
                       "एयरलाइन", "से", "चाहिए", "है", "मुझे", "वाली", "की", "का", "में", "only", "sirf", "सिर्फ")
_PARTS = {"services": _set("services", "service", "seva", "सेवा", "सर्विस"),
          "flight": _SERVICE_WORDS["flight"], "train": _SERVICE_WORDS["train"], "hotel": _SERVICE_WORDS["hotel"],
          "travellers": _set("travellers", "traveller", "travelers", "traveler", "yatri", "yatriyon", "log", "logon",
                             "naam", "names", "name", "umar", "age", "ages", "यात्री", "यात्रियों", "नाम", "उम्र", "लोग"),
          "phone": _set("phone", "number", "mobile", "फोन", "नंबर", "नम्बर", "मोबाइल")}


def _one(found: List[str]) -> Optional[str]:
    return found[0] if len(found) == 1 else None


def parse_choice(qid: str, text: str) -> Any:
    """The answer to a tap question, or None. Never guesses between two choices."""
    toks = tokens(text)
    sset = set(toks)
    if qid == "services":
        found = services_in(toks)
        return found or None
    if qid in ("flight_time", "train_time"):
        found = _one([k for k, ws in _TIMES.items() if sset & ws])
        return found or (BF.ANY if is_decide(toks) else None)
    if qid == "train_class":
        if sset & _SLEEPER:
            return "SL"
        found = sorted({_CLASS_NUM[toks[i - 1]] for i in range(1, len(toks)) if toks[i] in _AC and toks[i - 1] in _CLASS_NUM})
        if not found and "first" in sset and "class" in sset:
            found = ["1A"]
        return _one(found) or (BF.ANY if is_decide(toks) else None)
    if qid == "hotel_type":
        found = []
        if sset & _BUDGET:
            found.append("budget")
        nums = [n for n in numbers_in(toks)] + [_CLASS_NUM_STAR.get(t) for t in toks if t in _CLASS_NUM_STAR]
        if sset & _STAR or "+" in text:
            if 3 in nums:
                found.append("3star")
            if any(n and n >= 4 for n in nums):
                found.append("4plus")
        if sset & _LUXURY:
            found.append("4plus")
        return _one(sorted(set(found))) or (BF.ANY if is_decide(toks) else None)
    if qid == "hotel_rooms":
        nums = numbers_in(toks)
        if len(nums) == 1:
            return nums[0]
        return BF.ANY if is_decide(toks) else None
    if qid == "train_tatkal":
        said = yes_no(text)
        if said:
            return said
        if sset & _NO_WORDS:
            return "no"
        return BF.ANY if is_decide(toks) else None
    if qid == "flight_airline":
        if sset & _CHEAPEST:
            return "cheapest"
        if is_decide(toks):
            return BF.ANY
        rest = [t for t in toks if t not in _AIRLINE_FILLER]
        if any(other_script(t) for t in rest):
            return None                           # not understood: never stored
        if not rest:
            return "__ask_airline__"            # "koi khaas airline" without a name
        return " ".join(w.capitalize() if w.isascii() else w for w in rest)
    return None


_CLASS_NUM_STAR = {w: n for w, n in (("three", 3), ("teen", 3), ("थ्री", 3), ("तीन", 3), ("four", 4), ("char", 4),
                                     ("chaar", 4), ("फोर", 4), ("चार", 4), ("five", 5), ("paanch", 5), ("panch", 5),
                                     ("फाइव", 5), ("पांच", 5), ("seven", 7), ("सात", 7))}
_CLASS_NUM_STAR = {canon(k): v for k, v in _CLASS_NUM_STAR.items()}


def other_script(text: str) -> bool:
    """Letters outside Latin / Devanagari (e.g. Ol Chiki "ᱩᱢᱟᱱᱟᱛᱷ" from speech-to-text): not understood."""
    return any(BF._is_letter(ch) and not BF._allowed_letter(ch) for ch in text or "")


def parse_part(text: str) -> Optional[str]:
    toks = set(tokens(text))
    return _one([p for p, ws in _PARTS.items() if toks & ws])


# ---------------- the model, only to extract a name / age / phone that code could not read

_EXTRACT_TOOL = {"type": "function", "function": {
    "name": "booking_answer",
    "description": "What the user SAID in answer to the booking question. Use null for anything not said. Never guess.",
    "parameters": {"type": "object", "properties": {
        "name": {"type": ["string", "null"], "description": "The person's name copied exactly as written in the message (same script). Not a place, not a number."},
        "age": {"type": ["integer", "null"], "description": "The age in years, only if the user said it."},
        "phone_digits": {"type": ["string", "null"], "description": "The phone number's digits in the order said, digits only."},
    }, "required": ["name", "age", "phone_digits"]}}}


def model_extract(text: str, what: str) -> Dict[str, Any]:
    """One small call. Returns {} on any failure (the user is asked again)."""
    try:
        from openai_client import chat_tools
        msgs = [{"role": "system", "content": (
            "Extract ONLY what the user actually said in answer to a travel booking question about a traveller's "
            f"{what}. Copy a name exactly as written. Convert spoken numbers (Hindi, Hinglish or English) to digits. "
            "Never invent or guess a value: use null.")},
                {"role": "user", "content": text}]
        answer = chat_tools(msgs, [_EXTRACT_TOOL], tool_choice="required", temperature=0, timeout=8, reasoning_effort="low")
        call = next((c for c in answer.get("tool_calls") or [] if c.get("name") == "booking_answer"), None)
        return call.get("arguments") or {} if call else {}
    except Exception as err:
        logger.info("[BOOKING FLOW] event=model_extract ok=false err=%s", type(err).__name__)
        return {}


def _said_in(name: str, text: str) -> bool:
    """The model's name must be words the user said (it may not invent or transliterate one)."""
    said = set(tokens(text))
    return bool(name) and all(w in said for w in tokens(name))


# ---------------- one voice turn

def _value_for(s: BF.BookingState, qid: str, text: str, extract=model_extract) -> Tuple[Any, Optional[int], bool]:
    """(value, age_too, model_used). value None = not understood."""
    toks = tokens(text)
    if qid.endswith("_age_confirm"):
        said = yes_no(text)
        if said:
            return said, None, False
        nums = numbers_in(toks)
        return ("__new_age__", nums[0], False) if len(nums) == 1 else (None, None, False)
    if qid in ("phone_ok", "review"):
        if qid == "phone_ok":
            digits = phone_digits(text)
            if digits and len(digits) >= 9:           # a new number instead of yes / no
                return "__new_phone__:" + digits, None, False
        said = yes_no(text)
        if qid == "review" and said != "yes":
            part = parse_part(text)
            if part:
                return f"change:{part}", None, False
        return said, None, False
    if qid == "change":
        part = parse_part(text)
        return (f"change:{part}" if part else None), None, False
    t = BF._traveller(qid)
    if t and t[1] == "name":
        if yes_no(text):                          # a bare "haan" / "nahi" is not a name
            return None, None, False
        if is_decide(toks):
            return BF.ANY, None, False
        if other_script(text):
            return "__name_unclear__", None, False
        name, age, unsure = name_and_age(text)
        if name and not unsure and BF.clean_name(name):
            return name, age, False
        got = extract(text, "name")
        mname = got.get("name") if isinstance(got.get("name"), str) else None
        if mname and _said_in(mname, text):
            mage = got.get("age") if isinstance(got.get("age"), int) and not isinstance(got.get("age"), bool) else None
            return mname, mage, True
        return name, None, True        # checked by booking_flow (letters only): a bad name gets the name error
    if t and t[1] == "age":
        if is_decide(toks):
            return BF.ANY, None, False
        nums = numbers_in(toks)
        if len(nums) == 1:
            return nums[0], None, False
        got = extract(text, "age")
        age = got.get("age")
        return (age if isinstance(age, int) and not isinstance(age, bool) else None), None, True
    if qid == "phone":
        if is_decide(toks):
            return BF.ANY, None, False
        digits = phone_digits(text)
        if digits:
            return digits, None, False
        got = extract(text, "phone number")
        d = got.get("phone_digits")
        d = "".join(ch for ch in d if ch.isdigit()) if isinstance(d, str) else None
        return (d or "__bad_phone__"), None, True
    if qid == "services" and is_decide(toks):
        return None, None, False
    return parse_choice(qid, text), None, False


def _result(text: str, qid: str, **kw):
    from voice.agent import AgentResult
    return AgentResult(text, ui_actions=[dict(REFRESH)], action="booking", step=re.sub(r"^t\d+_", "traveller_", qid), **kw)


SCREEN_HINT = {"hi": "Aap screen par button bhi dabaa sakte hain.", "en": "You can also tap a button on the screen."}
TYPE_HINT = {"hi": "Aap screen par type bhi kar sakte hain.", "en": "You can also type it on the screen."}
TYPE_ONLY = {"hi": "Screen par type kar dijiye.", "en": "Please type it on the screen."}
NAME_UNCLEAR = {"hi": "Naam samajh nahi aaya. Dobara boliye, ya screen par type kar dijiye.",
                "en": "I didn't get the name. Please say it again, or type it on the screen."}
DECIDE_OFFER = {"hi": "Kya main 'aap decide karo' maan loon?", "en": "Shall I take it as 'you decide'?"}


def _allows_decide(qid: str) -> bool:
    return qid in BF.CHOICES or qid in ("flight_airline", "hotel_rooms")


def _miss_reply(s: BF.BookingState, qid: str, base: str, lang: str, name_unclear: bool = False) -> str:
    """Misses are counted per question (reset when the question changes): never the same reply three times.
    1st: the usual reply. 2nd: + a screen hint. 3rd: "aap decide karo?" where allowed, else type on the screen."""
    s.misses += 1
    n = s.misses
    t = BF._traveller(qid)
    if t and t[1] == "name":
        if n >= 2:
            return TYPE_ONLY[lang]
        return NAME_UNCLEAR[lang] if name_unclear else base
    if (t and t[1] == "age") or qid == "phone":
        return base if n == 1 else (f"{base} {TYPE_HINT[lang]}" if n == 2 else TYPE_ONLY[lang])
    if n == 1:
        return base
    if n >= 3 and _allows_decide(qid):
        s.decide_offer = qid
        return DECIDE_OFFER[lang]
    return f"{base} {SCREEN_HINT[lang]}"


def _mark_asked(redis_conn, user_id: str, s: BF.BookingState, conversation_id: str) -> None:
    s.voice_conversation, s.voice_asked_at = conversation_id, time.time()
    BF.save(redis_conn, user_id, s)


def handle(transcript: str, lang: str, *, user_id: str, conversation_id: str, trip, redis_conn,
           extract=model_extract):
    """An AgentResult for a booking turn, or None (not a booking turn: run_agent carries on as before)."""
    trip_id = getattr(trip, "id", None) if trip is not None else None
    asked_lang = lang
    if not trip_id:
        return _result(NO_TRIP[lang], "no_trip") if is_trigger(transcript) else None
    s = BF.load(redis_conn, user_id, trip_id)
    answering = (s is not None and s.voice_conversation == conversation_id
                 and time.time() - s.voice_asked_at <= ANSWER_WINDOW_S)
    if not answering:
        if not is_trigger(transcript):
            return None
        if is_cancel(transcript):              # "booking cancel karo"
            had = BF.cancel(redis_conn, user_id, trip_id)
            return _result(BF.CANCELLED[lang], "cancel") if had else None
        from voice import pending as P
        P.clear(redis_conn, user_id, conversation_id)   # a new topic: a waiting Confirm card no longer takes "haan"
        resumed = s is not None
        if s is None:
            from database import get_db_context
            from ownership import find_owned_trip
            try:
                with get_db_context() as db:       # read only: nothing is written to the database
                    db_trip = find_owned_trip(db, trip_id, user_id)
                    if db_trip is None:
                        return _result(NO_TRIP[lang], "no_trip")
                    s = BF.start(redis_conn, db, user_id, db_trip, services_in(tokens(transcript)))
                    s.voice_lang = asked_lang
            except BF.BookingError as err:
                return _result(BF.ERRORS[lang][err.code], "refused")
        if resumed:                             # a resumed flow keeps the language it was started in
            lang = s.voice_lang if s.voice_lang in BF.PROMPTS else lang
        qid = BF.current_question(s)
        _mark_asked(redis_conn, user_id, s, conversation_id)
        text = _with_intro(BF.prompt_for(s, qid, lang, spoken=True), qid, None, lang)
        return _result(f"{RESUMED[lang]} {text}" if resumed else text, qid)

    lang = s.voice_lang if s.voice_lang in BF.PROMPTS else lang   # a bare "Rahul" / "34" doesn't switch language
    if is_cancel(transcript):
        BF.cancel(redis_conn, user_id, trip_id)
        return _result(BF.CANCELLED[lang], "cancel")

    qid = BF.current_question(s)
    if s.miss_question != qid:                  # a new question: the miss count starts again
        s.misses, s.miss_question, s.decide_offer = 0, qid, None
    if s.decide_offer == qid:                   # we asked "Kya main 'aap decide karo' maan loon?"
        said = yes_no(transcript)
        s.decide_offer = None
        if said == "no":
            s.misses = 0
            _mark_asked(redis_conn, user_id, s, conversation_id)
            return _result(BF.prompt_for(s, qid, lang, spoken=True), qid)
        if said == "yes":
            BF.save(redis_conn, user_id, s)
            transcript = "aap decide karo"
    value, age_too, model_used = _value_for(s, qid, transcript, extract)
    if value == "__new_age__":
        BF.answer(redis_conn, user_id, trip_id, qid, "no")
        s, out = BF.answer(redis_conn, user_id, trip_id, BF.current_question(BF.load(redis_conn, user_id, trip_id)), age_too)
    elif isinstance(value, str) and value.startswith("__new_phone__:"):
        BF.answer(redis_conn, user_id, trip_id, qid, "no")
        s, out = BF.answer(redis_conn, user_id, trip_id, "phone", value.split(":", 1)[1])
    elif value == "__ask_airline__":
        _mark_asked(redis_conn, user_id, s, conversation_id)
        return _result(BF.ERRORS[lang]["airline_name_needed"], qid)
    elif value is None or value == "__name_unclear__":
        reply = _miss_reply(s, qid, f"{UNCLEAR[lang]} {BF.prompt_for(s, qid, lang, spoken=True)}", lang,
                            name_unclear=value == "__name_unclear__")
        BF.log_event("voice_answer", s, step=re.sub(r"^t\d+_", "traveller_", qid), understood=False,
                     model_used=model_used, misses=s.misses)
        _mark_asked(redis_conn, user_id, s, conversation_id)
        return _result(reply, qid)
    else:
        if value == "__bad_phone__":
            value = "x"
        s, out = BF.answer(redis_conn, user_id, trip_id, qid, value)
        # "Rahul, 34 saal": the age was said with the name, so it answers the next question too.
        if out.ok and age_too is not None and s is not None and BF.current_question(s) == qid.replace("_name", "_age"):
            s, out = BF.answer(redis_conn, user_id, trip_id, BF.current_question(s), age_too)
    if model_used:
        BF.log_event("voice_answer", s, model_used=True, understood=True)
    if out.finished:
        return _result(BF.DONE[lang], "done")
    if s is None:
        return _result(BF.CANCELLED[lang], "expired")
    nxt = BF.current_question(s)
    _mark_asked(redis_conn, user_id, s, conversation_id)
    prompt = BF.prompt_for(s, nxt, lang, spoken=True)
    if not out.ok:
        if s.miss_question != nxt:
            s.misses, s.miss_question, s.decide_offer = 0, nxt, None
        err = BF.ERRORS[lang][out.error]
        base = err if out.error == "phone_invalid" else f"{err} {prompt}"   # the 10-digit rule said once
        reply = _miss_reply(s, nxt, base, lang, name_unclear=out.error == "name_script")
        _mark_asked(redis_conn, user_id, s, conversation_id)
        return _result(reply, nxt)
    return _result(_with_intro(prompt, nxt, qid, lang), nxt)


def _with_intro(prompt: str, nxt: str, previous: Optional[str], lang: str) -> str:
    """One short line when the traveller step starts: "Ab yatriyon ke naam aur umar. Yatri 1 ka naam?"."""
    if nxt == "t0_name" and previous != "t0_name":
        return f"{BF.PROMPTS[lang]['travellers_intro']} {prompt}"
    return prompt


def safe_handle(transcript: str, lang: str, **kw):
    """run_agent never raises: a crash here is logged (class name only) and the turn goes on as before."""
    try:
        return handle(transcript, lang, **kw)
    except Exception as err:
        logger.warning("[BOOKING FLOW] event=voice_crash err=%s", type(err).__name__)
        return None
