"""
A natural "yes" to a confirmation question, decided by plain code (no model call):
"सही है", "बना दो", "हाँ, बना दो", "haan bana dijiye", "ok chalo", "yes please go ahead".

is_positive_confirmation(text) is True only when ALL of these hold:
  a. at most MAX_WORDS words (punctuation and the danda don't count);
  b. at least one POSITIVE word or POSITIVE_PHRASES phrase;
  c. no NEGATIVE word (no / hold / change);
  d. every other word is in FILLER, so the sentence carries no new data: a city or place, a date or month,
     a number, people or budget words are never filler, so "haan, par chaar din ke liye" is not a plain yes.

The word lists below are the one place to add words. Spellings are matched in the canonical form that
voice.text_utils.words() produces (हाँ -> हां, नही -> नहीं), so one entry covers the spelling variants.
Used today only at the voice trip-draft confirmation (the read-back and the review page's "ya haan boliye").
"""
from typing import Iterable, List, Set, Tuple

from voice.text_utils import canon, words as tu_words

MAX_WORDS = 8

POSITIVE = (
    "haan", "han", "ha", "haa", "haanji", "hanji", "ji", "yes", "yeah", "yep", "yup", "ok", "okay", "theek", "thik",
    "sahi", "bilkul", "correct", "right", "done", "karo", "banao", "proceed", "chalo", "shuru", "confirm", "pakka",
    "हां", "हाँ", "हा", "हांजी", "जी", "यस", "ओके", "ठीक", "सही", "बिल्कुल", "करो", "बनाओ", "चलो", "शुरू", "कन्फर्म", "पक्का",
)
POSITIVE_PHRASES = (
    "kar do", "kar dijiye", "kar dijie", "bana do", "bana dijiye", "bana dijie", "go ahead",
    "कर दो", "कर दीजिए", "कर दीजिये", "बना दो", "बना दीजिए", "बना दीजिये",
)
NEGATIVE = (
    "nahi", "nahin", "nai", "no", "nope", "not", "mat", "ruko", "ruk", "rukiye", "wait", "badlo", "badal", "badliye",
    "change", "galat", "wrong", "cancel", "stop", "rehne", "rahne",
    "नहीं", "नही", "मत", "रुको", "रुक", "रुकिए", "बदलो", "बदल", "बदलिए", "गलत", "कैंसल", "रद्द", "रहने", "नो",
)
# Words that may come with the yes and carry no trip data (never a place, a number, a date, people or money).
FILLER = (
    "hai", "hain", "he", "please", "plz", "pls", "trip", "ab", "abhi", "toh", "to", "de", "do", "dijiye", "dijie",
    "kijiye", "kar", "bana", "it", "its", "it's", "now", "sab", "accha", "acha", "achha", "badhiya", "great", "perfect",
    "fine", "sure", "go", "ahead", "lets", "let's", "let", "us", "sir", "bhai", "aap", "ye", "yeh", "isko", "ise", "is",
    "all", "good", "thank", "thanks", "you", "details", "plan",
    "है", "हैं", "प्लीज", "ट्रिप", "अब", "अभी", "तो", "दे", "दो", "दीजिए", "दीजिये", "कीजिए", "कर", "बना", "सब", "अच्छा",
    "बढ़िया", "बढिया", "आप", "ये", "यह", "इसको", "इसे", "प्लान",
)


def _canon_set(items: Iterable[str]) -> Set[str]:
    return {canon(w) for w in items}


def _phrases(items: Iterable[str]) -> List[Tuple[str, ...]]:
    return [tuple(tu_words(p)) for p in items]


_POSITIVE = _canon_set(POSITIVE)
_NEGATIVE = _canon_set(NEGATIVE)
_FILLER = _canon_set(FILLER)
_POSITIVE_PHRASES = _phrases(POSITIVE_PHRASES)


def is_positive_confirmation(text: str) -> bool:
    words = tu_words(text)
    if not words or len(words) > MAX_WORDS:
        return False
    if set(words) & _NEGATIVE:
        return False
    in_phrase = set()
    for phrase in _POSITIVE_PHRASES:
        n = len(phrase)
        for i in range(len(words) - n + 1):
            if tuple(words[i:i + n]) == phrase:
                in_phrase.update(range(i, i + n))
    positive = bool(in_phrase) or any(w in _POSITIVE for w in words)
    if not positive:
        return False
    return all(i in in_phrase or w in _POSITIVE or w in _FILLER for i, w in enumerate(words))
