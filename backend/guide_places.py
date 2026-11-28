"""
What the tour guide may say about nearby places (hospital, medical shop, restaurant, cafe). Pure code: no network.

- PLACE_TYPE_RULES + filter_and_sort: which Google results count for a category, and their order.
- PLACES_SYSTEM_PROMPT: the only prompt of a nearby-place turn (the general prompts ask for tips and timings).
- BANNED_BRANDS / BANNED_CLAIMS + clean_places_text / PlaceSentenceGate: the check on the model's text, also while
  streaming: a sentence with an unsupported claim is dropped before anyone sees it. Clean text is never changed.
- facts_reply: the plain answer from the data, used when the check removed every place (or no model answered).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple

MIN_REVIEWS_FOR_RATING = 20      # a rating with fewer reviews is never mentioned in the text
MAX_EMERGENCY_OPTIONS = 2        # hospital replies: the nearest open one, then at most one more

# ------------------------------------------------------------------ which results count (Google place types)
#   keep:         a result must have one of these as its primary type or among its types ("*_hospital" etc. are
#                 Google's newer names for the same things)
#   shop:         primary types of a medicine shop. Hospital intent: dropped, unless fewer than `min_keep` results
#                 remain; then they are kept, after everything else. Pharmacy intent: the only ones kept.
#   not_pharmacy: primary types that make a result a hospital even if Google also lists "pharmacy" among its types
#   shop_names:   Google files some medicine shops as "medical_center" + "hospital" (seen: "... Medical & General
#                 Store"). Hospital intent treats a name with one of these, and none of hospital_names, as a shop.
PLACE_TYPE_RULES: Dict[str, Any] = {
    "hospital": {
        "keep": {"hospital", "general_hospital", "childrens_hospital", "doctor", "clinic", "medical_clinic",
                 "medical_center", "health"},
        "shop": {"pharmacy", "drugstore"},
        "shop_names": ("medical store", "medical hall", "medical shop", "medicos", "general store", "chemist",
                       "pharmacy", "drug store"),
        "hospital_names": ("hospital", "clinic", "nursing home", "dispensary", "health centre", "health center"),
        "min_keep": 2,
        # A full hospital: one of full_types, no minor_names, and either full_names in its name or MIN_REVIEWS_FOR_RATING
        # reviews (Google files dispensaries, dental technicians and unknown buildings as "hospital" too).
        "full_types": {"hospital", "general_hospital", "childrens_hospital"},
        "full_names": ("hospital", "nursing home", "medical college", "trauma", "chikitsal", "aspatal", "haspatal",
                       "अस्पताल", "हॉस्पिटल", "चिकित्सालय"),
        "minor_names": ("dispensary", "disp.", "dental", "dentist", "homoeo", "homeo", "ayush", "veterinary",
                        "pet ", "animal", "औषधालय"),
    },
    "pharmacy": {
        "shop": {"pharmacy", "drugstore"},
        "not_pharmacy": {"hospital", "general_hospital", "childrens_hospital", "doctor", "clinic", "medical_clinic",
                         "medical_center"},
    },
}


def _types(p: Dict[str, Any]) -> Tuple[str, set]:
    primary = p.get("primary_type") or ""
    return primary, set(p.get("types") or []) | ({primary} if primary else set())


def _is_shop_for_hospital(p: Dict[str, Any]) -> bool:
    rules = PLACE_TYPE_RULES["hospital"]
    if _types(p)[0] in rules["shop"]:
        return True
    name = (p.get("name") or "").lower()
    return any(w in name for w in rules["shop_names"]) and not any(w in name for w in rules["hospital_names"])


def is_full_hospital(p: Dict[str, Any]) -> bool:
    rules = PLACE_TYPE_RULES["hospital"]
    name = (p.get("name") or "").lower()
    if any(w in name for w in rules["minor_names"]):
        return False
    primary = _types(p)[0]
    if primary and primary not in rules["full_types"]:
        return False
    return any(w in name for w in rules["full_names"]) or (p.get("rating_count") or 0) >= MIN_REVIEWS_FOR_RATING


def filter_and_sort(category: str, found: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """
    (places in display order, how many really match the category). Each place gets "_shop": True for a medicine shop
    kept in a hospital result as a last resort.
    Hospital: full hospitals (open now, then unknown hours), then dispensaries, clinics and the rest (open now, then
    unknown), then whatever is closed (full hospitals first), then last-resort shops; each group by distance.
    Everything else: by distance. (A result without any type stays: Google was asked for this category only.)
    """
    if category == "hospital":
        rules = PLACE_TYPE_RULES["hospital"]
        usable = [p for p in found if not _types(p)[1] or _types(p)[1] & rules["keep"] or _is_shop_for_hospital(p)]
        shops = [p for p in usable if _is_shop_for_hospital(p)]
        real = [p for p in usable if not _is_shop_for_hospital(p)]
        order = {True: 0, None: 1, False: 2}

        def rank(p):
            return p.get("open_now") is False, not is_full_hospital(p), order[p.get("open_now")], p["distance_m"]

        out = [{**p, "_shop": False} for p in sorted(real, key=rank)]
        if len(real) < rules["min_keep"]:
            out += [{**p, "_shop": True} for p in sorted(shops, key=rank)]
        return out, len(real)
    if category == "pharmacy":
        rules = PLACE_TYPE_RULES["pharmacy"]

        def ok(p):
            primary, types = _types(p)
            return not types or primary in rules["shop"] or bool(types & rules["shop"] and primary not in rules["not_pharmacy"])

        found = [p for p in found if ok(p)]
    out = sorted(found, key=lambda p: p["distance_m"])
    return out, len(out)


INTERNAL_FIELDS = ("_shop", "types", "primary_type")     # never sent to the app


def public_place(p: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in p.items() if k not in INTERNAL_FIELDS}


# ------------------------------------------------------------------ the prompt

PLACES_SYSTEM_PROMPT = """
You are VoyageAI's travel guide. The traveler asked for a nearby place. The app found real places on Google and shows
them as cards under your reply.

RULES:
1. Name ONLY places listed in the VERIFIED PLACES block. Never add another place.
2. About each place you may use ONLY these facts from the block: name, distance, open status, rating together with its
   review count, address. Nothing else is known about it, so say nothing else about it.
3. Never invent phone numbers, opening hours or ratings. Say a place is open only if the block says "open now: yes".
   If it says "unknown", say its hours aren't available or leave it out. Never say "24x7", "24 hours" or "always open".
4. Mention a rating only if its review count is >= 20, and always together with the review count.
5. FORBIDDEN, even if the traveler asks or earlier messages did it:
   - price, or words like premium, cheap, luxury
   - quality: best, good treatment, tasty, popular, famous, great, reliable or any other praise
   - crowd or timing predictions (busy hours, best time to go)
   - delivery apps, or any brand, app or website that is not in the block
   - medical advice of any kind, including about medicines
6. 2-3 short sentences in clear English, or in Devanagari if the user asks for Hindi: the nearest one or two
   places with their distance and open status. Add nothing after that.
7. Plain sentences only: no coordinates, no lists, no suggestions for a next question, no <<<CHIPS>>> or <<<CARD>>>,
   no markdown, no code blocks (```).
"""

EMERGENCY_PLACES_RULES = """
EMERGENCY RULES (this turn):
- The app has already started the reply with the 112 / 108 line. Don't repeat those numbers.
- First sentence: the first place in the block (the nearest open hospital) by name and distance. If it isn't
  "open now: yes", say that its hours aren't available, or that it is closed. Never call a dispensary or a clinic a hospital.
- Then at most one more option. A place marked "medical shop" is not a hospital: say so if you name it.
- No delivery apps, no treatment claims, no advice about medicines, first aid or what to do meanwhile.
"""


def places_system_prompt(category: str) -> str:
    return PLACES_SYSTEM_PROMPT + (EMERGENCY_PLACES_RULES if category == "hospital" else "")


def fmt_distance(meters: Optional[int]) -> str:
    if meters is None:
        return "distance unknown"
    return f"{meters} m" if meters < 1000 else f"{meters / 1000:.1f} km"


def prompt_places(found: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The places the model gets. Hospital: only the first two (the cards show all of them)."""
    places = found.get("places") or []
    return places[:MAX_EMERGENCY_OPTIONS] if found.get("category") == "hospital" else places


def places_block(found: Dict[str, Any]) -> str:
    """The prompt block: name, distance, open now, rating (only with enough reviews), address. No phone."""
    where = f"near {found['label']}" if found.get("source") == "named" else "around the traveler's current location"
    lines = [f"VERIFIED PLACES (Google, in order of preference, {where}):"]
    for i, p in enumerate(prompt_places(found), 1):
        open_txt = {True: "yes", False: "no"}.get(p.get("open_now"), "unknown")
        count = p.get("rating_count") or 0
        if p.get("rating") is None:
            rating = "no rating"
        elif count < MIN_REVIEWS_FOR_RATING:
            rating = "not to be mentioned (too few reviews)"
        else:
            rating = f"{p['rating']} ({count} reviews)"
        lines.append(f"{i}. {p['name']} | {fmt_distance(p.get('distance_m'))} | open now: {open_txt} | rating: {rating}"
                     + (f" | address: {p['address']}" if p.get("address") else "")
                     + (" | medical shop, not a hospital" if p.get("_shop") else ""))
    if len(lines) == 1:
        lines.append("(nothing found)")
    return "\n".join(lines) + "\n\n"


# ------------------------------------------------------------------ the check on the model's text
# Edit these two lists to tune the check. Whole words, any case; Devanagari as plain text.

BANNED_BRANDS: Tuple[str, ...] = (
    "Blinkit", "Swiggy", "Instamart", "Zepto", "Zomato", "Uber", "Ola", "Rapido", "Practo", "1mg", "PharmEasy",
    "Netmeds", "ब्लिंकिट", "स्विगी", "इंस्टामार्ट", "ज़ेप्टो", "जेप्टो", "ज़ोमैटो", "जोमैटो", "उबर", "रैपिडो", "प्रैक्टो", "फार्मईज़ी", "नेटमेड्स",
)
BANNED_CLAIMS: Tuple[str, ...] = (          # regular expressions
    # price and class
    r"premium", r"luxur(?:y|ious)", r"cheap(?:er|est)?", r"affordable", r"expensive", r"budget[- ]friendly",
    r"sast[aei]", r"mehn?g[aei]", r"प्रीमियम", r"लग्ज़?री", r"सस्त[ाेी]", r"महंग[ाेी]",
    # quality and praise
    r"best", r"top (?:pick|choice|rated)", r"great (?:pick|choice|option|place|reviews?)",
    r"excellent", r"reliable", r"trusted", r"tasty", r"delicious", r"popular", r"famous", r"must[- ]try",
    r"(?:good|great|quality|proper) (?:treatment|care|service|food|coffee)", r"ambian?[cs]e", r"ambience",
    r"ac+h+(?:ch+)?[aei] (?:ilaa?j|treatment|care|service|khana|option|jagah)", r"badhiya", r"behtar(?:een)?",
    r"swadisht", r"mashhoor", r"अच्छा इलाज", r"बेहतरीन", r"बढ़िया", r"स्वादिष्ट", r"मशहूर", r"सबसे अच्छ[ाेी]",
    # crowd and timing predictions
    r"crowd(?:s|ed|y)?", r"peak (?:hours?|time|\w+ (?:hours?|rush|crowd))", r"rush", r"gets? (?:very )?busy", r"bheed",
    r"best time", r"भीड़",
    # delivery
    r"(?:quick |home |online |medicine )?delivery", r"order (?:online|medicines?)", r"डिलीवरी",
)

_WORDY = r"(?<![\w])(?:%s)(?![\w])"
_BANNED_RE = re.compile(unicodedata.normalize("NFC", _WORDY % "|".join(
    [re.escape(b).replace("1mg", r"1\s?mg") for b in BANNED_BRANDS] + list(BANNED_CLAIMS))), re.IGNORECASE)
_HELPLINE_RE = re.compile(r"\b112\b.*\b108\b|\b108\b.*\b112\b|(?:dial|call|helpline|ambulance)\W+(?:\w+\W+){0,3}(?:112|108)\b"
                          r"|\b(?:112|108)\b\W+(?:\w+\W+){0,2}(?:dial|call|helpline|ambulance)", re.IGNORECASE | re.DOTALL)

# A sentence ends at . ! ? । followed by a space, or at a line break; not after "Dr.", an initial or a list number.
_END_RE = re.compile(r"[.!?।]+[\"'”’)\]]*\s+|\n+")
_NO_END_RE = re.compile(r"(?:^|[\s(\"'])(?:dr|st|mr|mrs|ms|smt|pt|shri|prof|no|nr|opp|rd|approx|govt|disp|vs|e\.g|i\.e|[a-z]|\d{1,2})\.\s+$",
                        re.IGNORECASE)


def split_sentences(text: str) -> Tuple[List[str], str]:
    """(complete sentences with their trailing space, the unfinished rest). Joined, they are exactly `text`."""
    out, start = [], 0
    for m in _END_RE.finditer(text):
        piece = text[start:m.end()]
        if "\n" not in m.group() and _NO_END_RE.search(piece):
            continue
        out.append(piece)
        start = m.end()
    return out, text[start:]


def _short_name(name: str) -> str:
    return re.split(r"\s*[,|(\-–]\s*", name, maxsplit=1)[0].strip()


def known_names(found: Optional[Dict[str, Any]]) -> List[str]:
    """Names from the data (longest first). They may hold a banned word ("Premium Medical Store", a real "Tata 1mg")."""
    names = set()
    for p in (found or {}).get("places") or []:
        names.add(p["name"])
        if " " in _short_name(p["name"]):
            names.add(_short_name(p["name"]))
        if p.get("address"):
            names.add(p["address"])
    if (found or {}).get("label"):
        names.add(found["label"])
    return sorted((n for n in names if n), key=len, reverse=True)


def is_banned(sentence: str, names: Iterable[str] = (), emergency: bool = False) -> bool:
    for n in names:
        sentence = sentence.replace(n, "§")
    sentence = unicodedata.normalize("NFC", sentence)
    return bool(_BANNED_RE.search(sentence) or (emergency and _HELPLINE_RE.search(sentence)))


class PlaceSentenceGate:
    """Streaming check: feed() returns only complete sentences that pass, finish() the rest. Emergency turns also lose
    a repeated 112/108 sentence (the app puts that line first)."""

    def __init__(self, found: Optional[Dict[str, Any]]) -> None:
        self._names = known_names(found)
        self._emergency = bool(found) and found.get("category") == "hospital"
        self._buf = ""
        self.dropped = 0

    def _pass(self, sentences: Iterable[str]) -> str:
        out = []
        for s in sentences:
            if is_banned(s, self._names, self._emergency):
                self.dropped += 1
            else:
                out.append(s)
        return "".join(out)

    def feed(self, piece: str) -> str:
        self._buf += piece or ""
        done, self._buf = split_sentences(self._buf)
        return self._pass(done)

    def finish(self) -> str:
        rest, self._buf = self._buf, ""
        return self._pass([rest]) if rest else ""


def _names_a_place(text: str, places: List[Dict[str, Any]]) -> bool:
    low = text.lower()
    return any(n and n.lower() in low for p in places for n in (p["name"], _short_name(p["name"])))


def clean_places_text(text: str, found: Dict[str, Any], message: str = "") -> Tuple[str, int]:
    """(text without the unsupported sentences, how many were dropped). Clean text comes back unchanged. If what is
    left names none of the places (hospital: not the first one), the plain facts are the answer instead."""
    gate = PlaceSentenceGate(found)
    out = gate.feed(text) + gate.finish()
    if not gate.dropped:
        return text, 0
    out = out.strip()
    places = prompt_places(found)
    need = places[:1] if found.get("category") == "hospital" else places
    if not out or not _names_a_place(out, need):
        out = facts_reply(found, message)
    return out, gate.dropped


# Follow-up chips of a place turn come from code: a tapped chip is sent as the next question, so it must be one the app
# can answer from Google again (a model's "Other options" or "Menu options" would be answered without any data).
_NEXT_PLACE = {"hospital": "Medical shop", "pharmacy": "Nearest hospital", "cafe": "Restaurants", "restaurant": "Cafes"}


def place_chips(found: Dict[str, Any]) -> List[str]:
    what = _NEXT_PLACE.get(found.get("category") or "")
    if not what:
        return []
    if found.get("source") == "named" and found.get("label"):
        return [f"{what} near {found['label']}"]
    return [what if what == "Nearest hospital" else f"{what} near me"]


# ------------------------------------------------------------------ the answer straight from the data

_HINGLISH_RE = re.compile(r"\b(hai|hain|kahan|kaha|kahaan|paas|mujhe|mere|mera|meri|batao|bataiye|chahiye|koi|ke|ki|ka|"
                          r"dikhao|sabse|nazdeek|yahan|milega|milegi|khula|bulao)\b", re.IGNORECASE)


def reply_lang(message: str) -> str:
    if re.search(r"[\u0900-\u097F]", message or ""):
        return "hi"
    return "hinglish" if _HINGLISH_RE.search(message or "") else "en"


_FACTS = {
    "hi": ("{n}, {d} दूर", {True: "अभी खुला है", False: "अभी बंद है", None: "खुलने का समय उपलब्ध नहीं है"}, "; ", "।", "दूसरा विकल्प: "),
    "en": ("{n}, {d} away", {True: "open now", False: "closed now", None: "hours not available"}, "; ", ".", "Another option: "),
}
_SHOP_NOTE = {"hi": " (मेडिकल शॉप)", "en": " (medical shop)"}


def facts_reply(found: Dict[str, Any], message: str = "") -> str:
    """The first two places: name, distance, open status. '' without places."""
    lang = "hi" if reply_lang(message) == "hi" else "en"
    pattern, opens, sep, end, second = _FACTS[lang]
    out = []
    for i, p in enumerate((found.get("places") or [])[:2]):
        name = p["name"] + (_SHOP_NOTE[lang] if p.get("_shop") else "")
        out.append((second if i else "") + pattern.format(n=name, d=fmt_distance(p.get("distance_m")))
                   + sep + opens[p.get("open_now")] + end)
    return " ".join(out)
