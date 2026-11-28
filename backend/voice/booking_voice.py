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
NO_TRIP = {"hi": "Pehle trip kholiye.", "en": "Please open a trip first.", "bn": "আগে একটা ট্রিপ খুলুন।"}
UNCLEAR = {"hi": "Samajh nahi aaya.", "en": "I didn't get that.", "bn": "বুঝতে পারলাম না।"}
RESUMED = {"hi": "Booking wahin se:", "en": "Continuing the booking:", "bn": "বুকিং আগের জায়গা থেকে:"}
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
# The word "age" ("रोहन, उमर बाईस साल"). Only a label when a number is next to it (see _drop_age_labels); otherwise
# it is a name ("Umar Farooq", "उमर फारूक", "मेरा नाम उमर है").
_AGE_LABELS = _set("umar", "umr", "umra", "age", "उमर", "उम्र", "उमृ", "उम्")


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
    "yeh", "old", "ji", "sir", "pehla", "pehle", "dusra", "yatri", "traveller", "traveler",
    "bachche", "bachcha", "bachchi", "beta", "beti", "child", "the", "of", "and", "aged", "naam", "called",
    "मेरा", "मेरी", "नाम", "है", "हैं", "उनका", "उनकी", "उसका", "उसकी", "इनका", "इनकी", "और", "वो", "वह", "यह", "ये",
    "का", "की", "के", "जी", "मैं", "पहले", "पहला", "यात्री", "बच्चे", "बच्चा", "बच्ची", "बेटा", "बेटी")


# "Yatri 1 ka naam Roshan", "रात्रि एक का नाम रौशन" (STT for "यात्री एक"), "नाम है रोशन, सिर्फ रोशन", "भाई, नाम है रोशन":
#  - a leading "yatri <number> (ka)" (and its mishearings) is never a name or an age;
#  - after a naam marker the name is the words that follow it, up to "hai / है / uska" (words before are dropped);
#  - address / filler words are dropped and a word is never repeated.
_NAME_MARKERS = _set("naam", "name", "नाम")
_NAME_STOP = _set("hai", "hain", "है", "हैं", "tha", "था", "uska", "uski", "unka", "unki", "उसका", "उसकी", "उनका", "उनकी")
_YATRI_LIKE = _set("yatri", "yaatri", "yatree", "raatri", "ratri", "traveller", "traveler", "passenger",
                   "यात्री", "यात्रि", "रात्री", "रात्रि")
_LEAD_LINK = _set("ka", "ki", "ke", "ko", "का", "की", "के", "को")
_NAME_EXTRA_FILLER = _set("bhai", "bhaiya", "sirf", "bas", "ji", "uska", "uski", "wala", "wali", "only", "just",
                          "भाई", "भैया", "सिर्फ", "बस", "जी", "उसका", "उसकी", "वाला", "वाली")


def _strip_lead_in(toks: List[str]) -> List[str]:
    """Drops a leading "yatri 1 (ka)" / "रात्रि एक का" so its number is never taken as an age."""
    for i, t in enumerate(toks[:3]):
        if t in _YATRI_LIKE and i + 1 < len(toks) and (toks[i + 1].isdigit() or toks[i + 1] in NUMBER_WORDS
                                                       or toks[i + 1] in _EN_UNITS):
            j = i + 2
            if j < len(toks) and toks[j] in _LEAD_LINK:
                j += 1
            return toks[:i] + toks[j:]
    return toks


def _name_word(t: str) -> bool:
    return not (t.isdigit() or t in NUMBER_WORDS or t in _EN_UNITS or t in _EN_TENS or t in _NAME_FILLER
                or t in _AGE_UNITS or t in _NAME_EXTRA_FILLER)


def _is_number(t: str) -> bool:
    return t.isdigit() or t in NUMBER_WORDS or t in _EN_UNITS or t in _EN_TENS


def _drop_age_labels(toks: List[str]) -> List[str]:
    """Removes umar / उमर / age ... only where it labels an age: a number within the next 3 words (no other label word
    in between: "Umar, age 30" keeps the name Umar), or a number right before it ("बाईस साल उमर")."""
    out = []
    for i, t in enumerate(toks):
        if t in _AGE_LABELS:
            after = False
            for x in toks[i + 1:i + 4]:
                if x in _AGE_LABELS:
                    break
                if _is_number(x):
                    after = True
                    break
            before = i >= 1 and (_is_number(toks[i - 1]) or (toks[i - 1] in _AGE_UNITS and i >= 2 and _is_number(toks[i - 2])))
            if after or before:
                continue
        out.append(t)
    return out


def name_parts(toks: List[str]) -> Tuple[List[str], List[int], List[str]]:
    """(name words, numbers said for the age, the tokens the age was read from)."""
    toks = _drop_age_labels(_strip_lead_in(toks))
    name_seg, age_seg = toks, toks
    marker = next((i for i, t in enumerate(toks) if t in _NAME_MARKERS), None)
    if marker is not None:
        after = toks[marker + 1:]
        k = 0
        while k < len(after) and not _name_word(after[k]) and not after[k].isdigit() and after[k] not in NUMBER_WORDS:
            k += 1                                        # "naam HAI Roshan", "name IS Roshan"
        rest = after[k:]
        cut = next((i for i, t in enumerate(rest) if t in _NAME_STOP), len(rest))
        if any(_name_word(t) for t in rest[:cut]):
            name_seg, age_seg = rest[:cut], after
        else:                                              # "रोशन नाम है उसका": the name is before the marker
            name_seg = toks[:marker]
    words: List[str] = []
    for t in name_seg:
        if _name_word(t) and t not in words:
            words.append(t)
    return words, numbers_in(age_seg), age_seg


def name_and_age(text: str) -> Tuple[Optional[str], Optional[int], bool]:
    """(name, age, unsure). Code only: filler words and numbers are taken out; `unsure` = a word next to "saal"
    that we can't read as a number (it would end up inside the name)."""
    words, ages, age_seg = name_parts(tokens(text))
    unsure = bool(set(age_seg) & _AGE_UNITS) and not ages
    name = " ".join(w.capitalize() if w.isascii() else w for w in words) or None
    return name, (ages[0] if len(ages) == 1 else None), unsure or len(ages) > 1


# ---------------- choices

_TIMES = {"morning": _set("subah", "subha", "suba", "subeh", "morning", "savere", "sawere", "savera", "सुबह", "सवेरे",
                          "सवेरा", "सुबे"),
          "afternoon": _set("dopahar", "dopehar", "dupahar", "dopaher", "afternoon", "noon", "दोपहर", "दुपहर"),
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
                       "एयरलाइन", "से", "चाहिए", "है", "मुझे", "वाली", "की", "का", "में", "only", "sirf", "सिर्फ",
                       "ko", "को", "airways", "एयरलाइंस", "एयरवेज")
_PARTS = {"services": _set("services", "service", "seva", "सेवा", "सर्विस"),
          "flight": _SERVICE_WORDS["flight"], "train": _SERVICE_WORDS["train"], "hotel": _SERVICE_WORDS["hotel"],
          "travellers": _set("travellers", "traveller", "travelers", "traveler", "yatri", "yatriyon", "log", "logon",
                             "naam", "names", "name", "umar", "age", "ages", "यात्री", "यात्रियों", "नाम", "उम्र", "लोग"),
          "phone": _set("phone", "number", "mobile", "फोन", "नंबर", "नम्बर", "मोबाइल")}


def _one(found: List[str]) -> Optional[str]:
    return found[0] if len(found) == 1 else None


def parse_choice(qid: str, text: str, lang: Optional[str] = None) -> Any:
    """The answer to a tap question, or None. Never guesses between two choices."""
    toks = tokens(text)
    sset = set(toks)
    if qid == "services":
        found = services_in(toks)
        return found or None
    if qid in ("flight_time", "train_time"):
        # Only a short answer with exactly one time word and no digits ("dopahar", "subah ki flight"); a time word
        # inside a long sentence ("...3 din ke liye...") is never taken as the answer.
        hits = [t for t in toks if any(t in ws for ws in _TIMES.values())]
        if len(toks) <= 6 and len(hits) == 1 and not any(t.isdigit() for t in toks):
            return next(k for k, ws in _TIMES.items() if hits[0] in ws)
        return BF.ANY if is_decide(toks) else None
    if qid == "train_class":
        if sset & _SLEEPER:
            return "SL"
        found = sorted({_CLASS_NUM[toks[i - 1]] for i in range(1, len(toks)) if toks[i] in _AC and toks[i - 1] in _CLASS_NUM})
        if not found and "first" in sset and "class" in sset:
            found = ["1A"]
        return _one(found) or (BF.ANY if is_decide(toks) else None)
    if qid == "hotel_type":
        found = []
        if any(_has_phrase(toks, p) for p in _FREE_STAR):
            found.append("3star")                 # "three star" heard as "free star" (this question only)
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
        known = airlines_in(toks)
        if known:
            return known[0] if len(known) == 1 else None    # "IndiGo ya Air India": never pick one
        rest = [t for t in toks if t not in _AIRLINE_FILLER]
        if any(other_script(t, lang) for t in rest):
            return None                           # not understood: never stored
        if not rest:
            return "__ask_airline__"            # "koi khaas airline" without a name
        heard = " ".join(w.capitalize() if w.isascii() else w for w in rest)
        if BF.name_problem(heard, BF.AIRLINE_MAX, lang):
            return None
        return AIRLINE_CHECK + heard              # not a known airline: "<heard> airline? Sahi hai?" first
    return None


# ---------------- airlines (BF.AIRLINES) as they are said; plus speech-to-text mishearings seen in real tests,
# used at the airline question only ("IndiGo" heard as "हिंदी को").

AIRLINE_CHECK = "__airline_check__:"
# "Air India" heard as just "India" / "इंडिया" (and close spellings); "India Express" stays Air India Express.
_HEARD_AS = {"IndiGo": ("हिंदी को", "hindi ko"),
             "Air India": ("india", "indiya", "indya", "इंडिया", "इण्डिया", "इंडीया", "एयर इण्डिया", "एअर इण्डिया",
                           "एर इंडिया", "हेयर इंडिया", "hair india", "air indya", "एयरइण्डिया"),
             "Air India Express": ("india express", "indiya express", "इंडिया एक्सप्रेस", "इण्डिया एक्सप्रेस",
                                   "एर इंडिया एक्सप्रेस", "हेयर इंडिया एक्सप्रेस")}
_AIRLINE_PHRASES = sorted({(tuple(tokens(alias)), name) for name, aliases in BF.AIRLINES
                           for alias in aliases + (name,) + _HEARD_AS.get(name, ())}, key=lambda x: -len(x[0]))
_SAID_PHRASES = sorted({(tuple(tokens(alias)), name) for name, aliases in BF.AIRLINES
                        for alias in aliases + (name,)}, key=lambda x: -len(x[0]))


def airlines_in(toks: List[str], heard: bool = True) -> List[str]:
    """The known airlines said, longest form first ("air india express" is not also "air india").
    heard=False: only the airlines' own names (no mishearings such as a bare "India")."""
    used = [False] * len(toks)
    found: List[str] = []
    for phrase, name in (_AIRLINE_PHRASES if heard else _SAID_PHRASES):
        n = len(phrase)
        for i in range(len(toks) - n + 1):
            if tuple(toks[i:i + n]) == phrase and not any(used[i:i + n]):
                used[i:i + n] = [True] * n
                if name not in found:
                    found.append(name)
    return found


_CLASS_NUM_STAR = {w: n for w, n in (("three", 3), ("teen", 3), ("थ्री", 3), ("तीन", 3), ("four", 4), ("char", 4),
                                     ("chaar", 4), ("फोर", 4), ("चार", 4), ("five", 5), ("paanch", 5), ("panch", 5),
                                     ("फाइव", 5), ("पांच", 5), ("seven", 7), ("सात", 7))}
_CLASS_NUM_STAR = {canon(k): v for k, v in _CLASS_NUM_STAR.items()}
_FREE_STAR = _phrases("free star", "फ्री स्टार", "फ्री स्टार्स", "free stars")


def other_script(text: str, lang: Optional[str] = None) -> bool:
    """Letters outside Latin / Devanagari (e.g. Ol Chiki "ᱩᱢᱟᱱᱟᱛᱷ" from speech-to-text): not understood.
    A Bengali voice booking (lang "bn") also reads Bengali letters (booking_flow._allowed_letter)."""
    return any(BF._is_letter(ch) and not BF._allowed_letter(ch, lang) for ch in text or "")


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


# ---------------- a name correction: "संज नहीं, रोशन झा", "nahi, naam Roshan Jha hai", "name is Roshan Jha"

_FIX_NEG = _set("nahi", "nahin", "nai", "na", "no", "not", "galat", "wrong", "incorrect", "नहीं", "नही", "ना", "गलत")
_FIX_NAME = _set("naam", "name", "नाम")
_FIX_FILLER = _set("sahi", "सही", "correct", "actually", "matlab", "मतलब", "balki", "बल्कि", "to", "toh", "तो", "sorry",
                   "सॉरी", "hai", "है", "tha", "था", "nahi", "bolo", "boliye", "बोलो", "बोलिए", "likho", "लिखो")
_FIX_ASK = _phrases("naam badlo", "naam badliye", "naam badal", "naam badalna", "naam change", "change name",
                    "change the name", "नाम बदलो", "नाम बदलिए", "नाम बदलना", "नाम बदल", "नाम चेंज")
_FIX_BACK = _set("peeche", "piche", "pichhe", "peechhe", "pichhe", "पीछे", "back")
_DONT_KNOW = _set("pata", "maloom", "malum", "पता", "मालूम", "know")
_WHO = _set("yatri", "traveller", "traveler", "यात्री")
SAY_NAME = {"hi": "Sahi naam boliye.", "en": "Please say the correct name.", "bn": "সঠিক নামটা বলুন।"}


def name_fix(text: str, mode: str) -> Optional[Dict[str, Any]]:
    """A name correction, or None. mode "age": at that traveller's age question (a negation or "naam" word is
    enough); "confirm": at the age "sahi hai?" step (a new name is needed: a bare "nahi" stays the yes/no answer);
    "later": a later question before the review ("naam" must be said).
    Returns {"name": str|None, "age": int|None, "who": index|None, "ask": "name"|"again"}."""
    toks = tokens(text)
    sset = set(toks)
    if not toks or sset & _DONT_KNOW:
        return None
    who = None
    for i, t in enumerate(toks):                 # "yatri 2 ka naam galat hai"
        if t in _WHO:
            near = numbers_in(toks[i + 1:i + 2]) or numbers_in(toks[max(0, i - 1):i])
            if near and near[0] >= 1:
                who = near[0] - 1
                toks = toks[:max(0, i - 1)] + [x for x in toks[max(0, i - 1):i + 2] if x not in _WHO
                                               and not numbers_in([x])] + toks[i + 2:]
            break
    asks_again = any(_has_phrase(toks, p) for p in _FIX_ASK) or (mode == "age" and sset & _FIX_BACK and len(toks) <= 3)
    if asks_again:
        return {"name": None, "age": None, "who": who, "ask": "again"}
    neg = [i for i, t in enumerate(toks) if t in _FIX_NEG]
    has_naam = bool(sset & _FIX_NAME)
    if not neg and not has_naam:
        return None
    if mode == "later" and not has_naam:
        return None
    seg = toks[neg[-1] + 1:] if neg else toks
    parsed, nums, _ = name_parts(seg)
    words = [t for t in parsed if t not in _FIX_NEG and t not in _FIX_FILLER]
    if not words:
        if nums or mode == "confirm":
            return None                          # "nahi, 25" is an age; at "sahi hai?" a bare "nahi" is the answer
        return {"name": None, "age": None, "who": who, "ask": "name"}
    name = " ".join(w.capitalize() if w.isascii() else w for w in words)
    return {"name": name, "age": nums[0] if len(nums) == 1 else None, "who": who, "ask": None}


def _fix_target(s: BF.BookingState, qid: str) -> Optional[Tuple[int, str]]:
    """Whose name a correction is for and how strict to be; None where no correction is taken (name questions,
    the services questions, the review)."""
    confirm = qid.endswith("_age_confirm")
    t = BF._traveller(qid[: -len("_confirm")] if confirm else qid)
    if t and t[1] == "age":
        return t[0], ("confirm" if confirm else "age")
    if qid in ("phone", "phone_ok"):
        named = [i for i, x in enumerate(s.travellers) if x.get("name")]
        return (named[-1], "later") if named else None
    return None


# ---------------- a voice edit at the review: "एयरलाइन का नाम एयर इंडिया", "hotel 4 star", "phone number badlo"
# The sentence names ONE field: only that question is asked again (or the new value said with it is applied through
# the usual checks), every other answer stays, and the review is read again. A field word wins over "naam":
# "एयरलाइन का नाम" is the airline. The travellers only with a yatri word plus naam / umar / a change word, or
# "naam badlo". Nothing recognised: None (the review's usual answers: yes / no / "Samajh nahi aaya").

_F_AIRLINE = _set("airline", "airlines", "airways", "एयरलाइन", "एयरलाइंस", "एयरलाइन्स", "एयरवेज")
_F_TIME = _set("time", "timing", "samay", "waqt", "vakt", "टाइम", "टाइमिंग", "समय", "वक्त", "वक़्त")
_F_ROOMS = _set("kamra", "kamre", "kamron", "room", "rooms", "कमरा", "कमरे", "कमरों", "रूम", "रूम्स")
_F_CLASS = _set("class", "क्लास", "tier", "टियर", "coach", "कोच") | _SLEEPER
_F_TATKAL = _set("tatkal", "tatkaal", "तत्काल", "तत्कल")
_F_PHONE = _set("phone", "mobile", "फोन", "फ़ोन", "मोबाइल")
_F_NUMBER = _set("number", "नंबर", "नम्बर")
_F_PEOPLE = _set("yatri", "yatriyon", "yaatri", "traveller", "travellers", "traveler", "travelers", "passenger",
                 "यात्री", "यात्रियों", "यात्रि") | _YATRI_LIKE
_F_PEOPLE_WITH = _NAME_MARKERS | _AGE_LABELS | _set("badlo", "badal", "badalna", "badliye", "change", "galat",
                                                     "बदलो", "बदल", "बदलना", "बदलिए", "चेंज", "गलत")
_ALL_TIME_WORDS = set().union(*_TIMES.values())


def _time_value(toks: List[str]) -> Optional[str]:
    if set(toks) & _NAME_MARKERS:
        toks = [t for t in toks if t not in _YATRI_LIKE]
    keys = [k for t in toks for k, ws in _TIMES.items() if t in ws]
    if len(set(keys)) == 1:
        return keys[0]
    if keys and set(toks) & _FIX_NEG:
        return keys[-1]                           # "subah nahi, raat": the last one said
    return None


def _rooms_value(toks: List[str]) -> Optional[int]:
    # "do" / "दो" is also "kar do": a number only right before the rooms word ("do kamre").
    keep = [t for i, t in enumerate(toks) if t not in ("do", "दो") or (i + 1 < len(toks) and toks[i + 1] in _F_ROOMS)]
    nums = numbers_in(keep)
    return nums[0] if len(nums) == 1 else None


def _phone_value(toks: List[str]) -> Optional[str]:
    run: List[str] = []
    for t in toks + ["|"]:                      # the digits said in one run ("98765 43210", "nau aath ...")
        if t.isdigit() or t in _DIGIT_WORDS or t in _REPEAT or (t in NUMBER_WORDS and 10 <= NUMBER_WORDS[t] <= 99) \
                or t in _EN_TENS or t in _EN_UNITS:
            run.append(t)
            continue
        if run:
            got = BF.normalize_phone(phone_digits(" ".join(run)) or "")
            if got:
                return got
        run = []
    return None


def review_edit(s: BF.BookingState, text: str) -> Optional[Tuple[str, Any]]:
    """(field, value or None) for a sentence at the review that names a field, else None."""
    toks = tokens(text)
    if not toks:
        return None
    sset = set(toks)
    qids = BF.question_ids(s)
    pos: Dict[str, int] = {}

    def seen(field: str, words: set) -> None:
        at = next((i for i, t in enumerate(toks) if t in words), None)
        if at is not None and field in qids:
            pos.setdefault(field, at)

    said_flight, said_train = bool(sset & _SERVICE_WORDS["flight"]), bool(sset & _SERVICE_WORDS["train"])
    time_words = _F_TIME | _ALL_TIME_WORDS
    if sset & _NAME_MARKERS:
        time_words = time_words - _YATRI_LIKE     # "रात्रि एक का नाम" is "यात्री एक का नाम", not "night"
    if sset & time_words:
        if said_train and not said_flight:
            seen("train_time", time_words)
        elif said_flight and not said_train:
            seen("flight_time", time_words)
        elif not said_flight and not said_train:
            times = [q for q in ("flight_time", "train_time") if q in qids]
            if len(times) == 1:
                seen(times[0], time_words)
    seen("flight_airline", _F_AIRLINE)
    if "flight_airline" in qids and "flight_airline" not in pos and airlines_in(toks, heard=False):
        pos["flight_airline"] = 0                 # "मुझे बस एयर इंडिया चेंज करना था"
    if said_flight and "flight_time" not in pos:
        seen("flight_airline", _SERVICE_WORDS["flight"])
    seen("hotel_rooms", _F_ROOMS)
    if "hotel_rooms" not in pos:
        seen("hotel_type", _SERVICE_WORDS["hotel"] | _STAR | _LUXURY)
    seen("train_class", _F_CLASS)
    seen("train_tatkal", _F_TATKAL)
    if "phone" in qids:
        at = next((i for i, t in enumerate(toks) if t in _F_PHONE), None)
        if at is not None:
            pos["phone"] = at
    people = bool(sset & _F_PEOPLE) and bool(sset & _F_PEOPLE_WITH) or any(_has_phrase(toks, p) for p in _FIX_ASK)
    if not pos and not people and "phone" in qids and sset & _F_NUMBER:
        pos["phone"] = next(i for i, t in enumerate(toks) if t in _F_NUMBER)
    if pos:
        field = min(pos, key=pos.get)             # one change per turn: the field named first
        if field == "flight_airline":
            known = airlines_in(toks)
            value = known[0] if len(known) == 1 else ("cheapest" if sset & _CHEAPEST else None)
        elif field in ("flight_time", "train_time"):
            value = _time_value(toks)
        elif field == "hotel_rooms":
            value = _rooms_value(toks)
        elif field == "phone":
            value = _phone_value(toks)
        elif field in ("hotel_type", "train_class"):
            got = parse_choice(field, text)
            value = got if got not in (None, BF.ANY) else None
        else:
            value = None
        return field, value
    if people:
        for i, t in enumerate(toks):              # "yatri 2 ka naam badlo": only that traveller
            if t in _F_PEOPLE:
                near = numbers_in(toks[i + 1:i + 2])
                if near and 1 <= near[0] <= s.traveller_count():
                    return f"traveller:{near[0] - 1}", None
        return "travellers", None
    return None


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
            if part and part != "travellers":     # the travellers only through review_edit (never a bare "naam")
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
        if other_script(text, s.voice_lang):
            return "__name_unclear__", None, False
        name, age, unsure = name_and_age(text)
        if name and not unsure and BF.clean_name(name, lang=s.voice_lang):
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
        if len(nums) == 1 or (nums and len(set(nums)) == 1):
            return nums[0], None, False
        if len(set(nums)) > 1:                      # "पच्चीस, पचहत्तर वर्ष": never pick one silently
            return "__age_guess__", nums[-1], False
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
    return parse_choice(qid, text, s.voice_lang), None, False


OPEN_SCREEN = {"type": "navigate", "to": "/trip/booking"}   # allowlisted in the app's uiActions.ts only (not pages.py)


def _result(text: str, qid: str, open_screen: bool = False, **kw):
    """open_screen: on start / resume and after the services answer only (the app skips it if already there)."""
    from voice.agent import AgentResult
    actions = ([dict(OPEN_SCREEN)] if open_screen else []) + [dict(REFRESH)]
    return AgentResult(text, ui_actions=actions, action="booking", step=re.sub(r"^t\d+_", "traveller_", qid), **kw)


SCREEN_HINT = {"hi": "Aap screen par button bhi dabaa sakte hain.", "en": "You can also tap a button on the screen.", "bn": "স্ক্রিনের বোতামও চাপতে পারেন।"}
TYPE_HINT = {"hi": "Aap screen par type bhi kar sakte hain.", "en": "You can also type it on the screen.", "bn": "স্ক্রিনে টাইপও করতে পারেন।"}
TYPE_ONLY = {"hi": "Screen par type kar dijiye.", "en": "Please type it on the screen.", "bn": "স্ক্রিনে টাইপ করে দিন।"}
NAME_UNCLEAR = {"hi": "Naam samajh nahi aaya. Dobara boliye, ya screen par type kar dijiye.",
                "en": "I didn't get the name. Please say it again, or type it on the screen.", "bn": "নামটা বুঝতে পারলাম না। আবার বলুন, অথবা স্ক্রিনে টাইপ করে দিন।"}
AGE_GUESS = {"hi": "Umar {age} hai? Sahi hai?", "en": "Is the age {age}? Is that right?", "bn": "বয়স {age}? ঠিক আছে?"}
AIRLINE_ASK = {"hi": "{name} airline? Sahi hai?", "en": "{name} airline? Is that right?", "bn": "{name} এয়ারলাইন? ঠিক আছে?"}
DECIDE_OFFER = {"hi": "Kya main 'aap decide karo' maan loon?", "en": "Shall I take it as 'you decide'?", "bn": "তাহলে কি 'আপনিই ঠিক করুন' ধরে নেব?"}


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
            except BF.RequestExists as err:     # one open request per trip: no new flow
                return _result(BF.already_text(err.request, lang), "request_exists")
            except BF.BookingError as err:
                return _result(BF.ERRORS[lang][err.code], "refused")
        if resumed:                             # a resumed flow keeps the language it was started in
            lang = s.voice_lang if s.voice_lang in BF.PROMPTS else lang
        qid = BF.current_question(s)
        _mark_asked(redis_conn, user_id, s, conversation_id)
        text = _with_intro(BF.prompt_for(s, qid, lang, spoken=True), qid, None, lang)
        return _result(f"{RESUMED[lang]} {text}" if resumed else text, qid, open_screen=True)

    lang = s.voice_lang if s.voice_lang in BF.PROMPTS else lang   # a bare "Rahul" / "34" doesn't switch language
    if is_cancel(transcript):
        BF.cancel(redis_conn, user_id, trip_id)
        return _result(BF.CANCELLED[lang], "cancel")

    qid = BF.current_question(s)
    if s.miss_question != qid:                  # a new question: the miss count starts again
        s.misses, s.miss_question, s.decide_offer, s.age_guess, s.airline_guess = 0, qid, None, None, None
    if s.age_guess is not None:                 # we asked "Umar 75 hai? Sahi hai?"
        said = yes_no(transcript)
        guess, s.age_guess = s.age_guess, None
        BF.save(redis_conn, user_id, s)
        if said == "no":
            _mark_asked(redis_conn, user_id, s, conversation_id)
            return _result(BF.prompt_for(s, qid, lang, spoken=True), qid)
        if said == "yes":
            transcript = str(guess)
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
    checked_airline = None
    if s.airline_guess is not None:             # we asked "<heard> airline? Sahi hai?"
        said = yes_no(transcript)
        guess, s.airline_guess = s.airline_guess, None
        BF.save(redis_conn, user_id, s)
        if said == "yes":
            checked_airline = guess
        elif said == "no":
            again = parse_choice(qid, transcript, s.voice_lang)          # "nahi, IndiGo"
            if not (isinstance(again, str) and (again in ("cheapest", BF.ANY) or BF.airline_name(again))):
                _mark_asked(redis_conn, user_id, s, conversation_id)
                return _result(BF.prompt_for(s, qid, lang, spoken=True), qid)
    target = _fix_target(s, qid) if s.age_guess is None and s.decide_offer is None else None
    fix = name_fix(transcript, target[1]) if target else None
    if fix is not None:
        who = fix["who"] if fix["who"] is not None and fix["who"] < s.traveller_count() else target[0]
        if target[1] == "later" or fix["who"] is not None:
            if not (who < len(s.travellers) and s.travellers[who].get("name")):
                fix = None                          # nobody's name to correct there: the usual answer
    if fix is not None:
        s, out = BF.correct_name(redis_conn, user_id, trip_id, who, fix["name"])
        if s is None:
            return _result(BF.CANCELLED[lang], "expired")
        nq = BF.current_question(s)
        if not out.ok:
            reply = NAME_UNCLEAR[lang] if out.error == "name_script" else f"{BF.ERRORS[lang][out.error]} {SAY_NAME[lang]}"
            _mark_asked(redis_conn, user_id, s, conversation_id)
            return _result(reply, qid)
        _mark_asked(redis_conn, user_id, s, conversation_id)
        if fix["name"] is None:
            reply = SAY_NAME[lang] if fix["ask"] == "name" else BF.prompt_for(s, nq, lang, spoken=True)
            return _result(reply, nq)
        if fix["age"] is not None and nq.endswith("_age"):
            s, out = BF.answer(redis_conn, user_id, trip_id, nq, fix["age"], lang=lang)
            if s is None:
                return _result(BF.CANCELLED[lang], "expired")
            nq = BF.current_question(s)
            _mark_asked(redis_conn, user_id, s, conversation_id)
            if not out.ok:
                return _result(f"{BF.ERRORS[lang][out.error]} {BF.prompt_for(s, nq, lang, spoken=True)}", nq)
        return _result(BF.prompt_for(s, nq, lang, spoken=True), nq)
    edit = review_edit(s, transcript) if qid == "review" else None
    if edit is not None and yes_no(transcript) == "yes" and (
            edit[1] is None or edit[1] == (s.phone if edit[0] == "phone" else s.answers.get(edit[0]))):
        edit = None                               # "phone number sahi hai", "IndiGo theek hai": the review's yes
    if edit is not None:
        field, new_value = edit
        s, done = BF.edit_field(redis_conn, user_id, trip_id, field)
        if s is None:
            return _result(BF.CANCELLED[lang], "expired")
        if done and new_value is not None:        # "airline Air India", "hotel 4 star": the usual checks
            s, out = BF.answer(redis_conn, user_id, trip_id, field, new_value, lang=lang)
            if s is None:
                return _result(BF.CANCELLED[lang], "expired")
        nq = BF.current_question(s)
        _mark_asked(redis_conn, user_id, s, conversation_id)
        prompt = BF.prompt_for(s, nq, lang, spoken=True)
        if done and new_value is not None and not out.ok:
            return _result(f"{BF.ERRORS[lang][out.error]} {prompt}", nq)
        return _result(_with_intro(prompt, nq, qid, lang), nq)
    if checked_airline is not None:
        value, age_too, model_used = checked_airline, None, False
    else:
        value, age_too, model_used = _value_for(s, qid, transcript, extract)
    if isinstance(value, str) and value.startswith(AIRLINE_CHECK):
        s.airline_guess = value[len(AIRLINE_CHECK):]
        _mark_asked(redis_conn, user_id, s, conversation_id)
        return _result(AIRLINE_ASK[lang].format(name=s.airline_guess), qid)
    if value == "__new_age__":
        BF.answer(redis_conn, user_id, trip_id, qid, "no")
        s, out = BF.answer(redis_conn, user_id, trip_id, BF.current_question(BF.load(redis_conn, user_id, trip_id)), age_too)
    elif isinstance(value, str) and value.startswith("__new_phone__:"):
        BF.answer(redis_conn, user_id, trip_id, qid, "no")
        s, out = BF.answer(redis_conn, user_id, trip_id, "phone", value.split(":", 1)[1])
    elif value == "__age_guess__":
        s.age_guess = age_too
        _mark_asked(redis_conn, user_id, s, conversation_id)
        return _result(AGE_GUESS[lang].format(age=age_too), qid)
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
        s, out = BF.answer(redis_conn, user_id, trip_id, qid, value, lang=lang)
        # "Rahul, 34 saal": the age was said with the name, so it answers the next question too.
        if out.ok and age_too is not None and s is not None and BF.current_question(s) == qid.replace("_name", "_age"):
            s, out = BF.answer(redis_conn, user_id, trip_id, BF.current_question(s), age_too)
    if model_used:
        BF.log_event("voice_answer", s, model_used=True, understood=True)
    if out.finished:
        # BR-1006: the request is saved; this conversation's old turns (and any draft / pending) are dropped so a later
        # "haan" can't rebuild an old trip draft. Only this conversation.
        from voice.agent import clear_memory
        clear_memory(redis_conn, user_id, conversation_id)
        return _result(BF.saved_text(out.request, lang), "done")
    if out.error == "save_failed":             # the Redis state is kept: "haan" again retries
        _mark_asked(redis_conn, user_id, s, conversation_id)
        return _result(BF.ERRORS[lang]["save_failed"], "review")
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
    return _result(_with_intro(prompt, nxt, qid, lang), nxt, open_screen=qid == "services")


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


# ---------------- Bengali (beta, feat/bengali): the same kinds of words, added to the sets above.
# Separate lists so the Hindi / English ones stay exactly as they were; tables built from the sets at import
# (_DIGIT_WORDS, _ALL_TIME_WORDS, the airline phrases, _F_CLASS, _F_PEOPLE, _F_PEOPLE_WITH) are rebuilt here.
# Not reviewed by a native speaker yet (docs/bengali_review.md).
from voice import bn_words as _BN  # noqa: E402

_BOOK |= _set("বুক", "বুকিং")
_SERVICE_WORDS["flight"] |= _set("ফ্লাইট", "প্লেন", "বিমান", "উড়োজাহাজ", "ফ্লাইটে")
_SERVICE_WORDS["train"] |= _set("ট্রেন", "ট্রেনে", "রেল", "রেলগাড়ি")
_SERVICE_WORDS["hotel"] |= _set("হোটেল", "হোটেলে", "হোটেলের")
_ALL_SERVICES |= _set("তিনটেই", "তিনটাই", "সবগুলো", "সবকটা")
_NOT_OURS |= _set("ক্যাব", "ট্যাক্সি", "অটো", "উবার", "ওলা", "টেবিল", "রেস্টুরেন্ট")
_CANCEL_PHRASES += _phrases("এখন না", "বাদ দিন", "বাদ দাও", "বুকিং বাতিল", "বন্ধ করুন", "বন্ধ করো")
_CANCEL_WORDS |= _set("বাতিল", "ক্যানসেল", "থাক")
_DECIDE_PHRASES += _phrases("আপনি ঠিক করুন", "আপনিই ঠিক করুন", "আপনি দেখুন", "আপনি দেখে নিন", "যা হোক",
                            "যেটা ভালো", "আপনার পছন্দ")
_DECIDE_WORDS |= _set("যেকোনো", "যেকোন")
_YES_EXTRA |= _set("চলবে", "হ্যাঁ", "হ্যা", "হাঁ", "ঠিক", "ওকে", "অবশ্যই", "সঠিক", "আছে")
_NO_WORDS |= _set("না", "নাহ", "নো", "ভুল", "নয়")
NUMBER_WORDS.update({canon(w): i for i, w in enumerate(_BN.BN_NUMBERS)})
NUMBER_WORDS.update({canon(w): n for w, n in _BN.BN_NUMBER_VARIANTS.items()})
_AGE_UNITS |= _set("বছর", "বছরের", "বছরে")
_AGE_LABELS |= _set("বয়স")
_REPEAT.update({canon("ডাবল"): 2, canon("ট্রিপল"): 3})
_PHONE_FILLER |= _set("আমার", "নম্বর", "নাম্বার", "ফোন", "মোবাইল", "হলো", "হল", "প্লাস", "এবং", "আর")
_NAME_FILLER |= _set("আমার", "নাম", "হলো", "হল", "ওর", "ওনার", "তার", "এবং", "আর", "প্রথম", "দ্বিতীয়", "যাত্রী",
                     "বাচ্চা", "ছেলে", "মেয়ে", "জি")
_NAME_MARKERS |= _set("নাম")
_YATRI_LIKE |= _set("যাত্রী")
_LEAD_LINK |= _set("এর", "র")
_NAME_EXTRA_FILLER |= _set("শুধু", "ভাই", "দাদা", "দিদি")
_TIMES["morning"] |= _set("সকাল", "সকালে", "সকালের", "ভোর", "ভোরে")
_TIMES["afternoon"] |= _set("দুপুর", "দুপুরে", "দুপুরের")
_TIMES["evening"] |= _set("সন্ধ্যা", "সন্ধ্যে", "সন্ধ্যায়", "সন্ধ্যার", "বিকেল", "বিকেলে")
_TIMES["night"] |= _set("রাত", "রাতে", "রাতের", "রাত্রে")
_SLEEPER |= _set("স্লিপার")
_AC |= _set("এসি", "টিয়ার", "ক্লাস")
_CLASS_NUM.update({**{w: "1A" for w in _set("ফার্স্ট", "এক", "প্রথম")},
                   **{w: "2A" for w in _set("সেকেন্ড", "দুই", "দ্বিতীয়")},
                   **{w: "3A" for w in _set("থার্ড", "তিন", "তৃতীয়")}})
_BUDGET |= _set("বাজেট", "সস্তা", "সস্তার")        # _CHEAPEST is the same set
_STAR |= _set("স্টার", "তারা")
_LUXURY |= _set("লাক্সারি", "বিলাসবহুল")
_AIRLINE_FILLER |= _set("কোনো", "বিশেষ", "এয়ারলাইন", "থেকে", "চাই", "আমার", "এর", "শুধু", "প্লিজ", "ফ্লাইট")
_CLASS_NUM_STAR.update({canon(k): v for k, v in (("তিন", 3), ("চার", 4), ("থ্রি", 3), ("ফোর", 4), ("পাঁচ", 5))})
_PARTS["services"] |= _set("সার্ভিস")
_PARTS["travellers"] |= _set("যাত্রী", "যাত্রীদের", "নাম", "বয়স", "লোক")
_PARTS["phone"] |= _set("ফোন", "নম্বর", "নাম্বার", "মোবাইল")
_F_AIRLINE |= _set("এয়ারলাইন")
_F_TIME |= _set("সময়", "টাইম")
_F_ROOMS |= _set("রুম", "ঘর")
_F_TATKAL |= _set("তৎকাল", "তাৎকাল")
_F_PHONE |= _set("ফোন", "মোবাইল")
_F_NUMBER |= _set("নম্বর", "নাম্বার")
_F_CLASS = _F_CLASS | _set("ক্লাস", "কোচ") | _SLEEPER
_F_PEOPLE = _F_PEOPLE | _set("যাত্রী", "যাত্রীদের") | _YATRI_LIKE
_F_PEOPLE_WITH = _F_PEOPLE_WITH | _NAME_MARKERS | _AGE_LABELS | _set("বদলান", "বদলাও", "পাল্টান", "ভুল", "চেঞ্জ")
_DONT_KNOW |= _set("জানি")
_FIX_NEG |= _set("না", "নয়", "ভুল")
_FIX_NAME |= _set("নাম")
_WHO |= _set("যাত্রী")
_ALL_TIME_WORDS = set().union(*_TIMES.values())
for _w, _d in list(NUMBER_WORDS.items()):
    if _d < 10:
        _DIGIT_WORDS.setdefault(_w, str(_d))
# Airlines as written in Bangla script (booking_flow.AIRLINES has the Latin / Devanagari forms).
BN_AIRLINES = {"IndiGo": ("ইন্ডিগো", "ইন্ডি গো"), "Air India": ("এয়ার ইন্ডিয়া", "এয়ারইন্ডিয়া"),
               "Air India Express": ("এয়ার ইন্ডিয়া এক্সপ্রেস",), "SpiceJet": ("স্পাইসজেট", "স্পাইস জেট"),
               "Akasa Air": ("আকাসা", "আকাসা এয়ার", "আকাশা এয়ার"), "Alliance Air": ("অ্যালায়েন্স এয়ার", "এলায়েন্স এয়ার"),
               "Star Air": ("স্টার এয়ার",), "Fly91": ("ফ্লাই 91", "ফ্লাই নাইন্টি ওয়ান")}
_BN_AIRLINE_PHRASES = {(tuple(tokens(alias)), name) for name, aliases in BN_AIRLINES.items() for alias in aliases}
_AIRLINE_PHRASES = sorted(set(_AIRLINE_PHRASES) | _BN_AIRLINE_PHRASES, key=lambda x: -len(x[0]))
_SAID_PHRASES = sorted(set(_SAID_PHRASES) | _BN_AIRLINE_PHRASES, key=lambda x: -len(x[0]))
