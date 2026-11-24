"""
Word handling for voice transcripts in Roman and Devanagari script (yes/no, "is this noise?", cancel).

normalize_text: NFC, lowercase, punctuation/symbols (. , ? ! । ॥ ; : quotes ...) -> spaces, spaces collapsed,
                plus a few Devanagari canonical forms so one word set covers the variants:
                  chandrabindu -> anusvara (हाँ == हां), nukta dropped (ज़रूर == जरूर), common spellings (नही -> नहीं).
                Vowel signs and other combining marks are kept: they are part of the word.
words:          the normalized text split into words. A word is a run of letters (L*) and marks (M*), so for Latin
                text this is exactly the old re.findall(r"[a-z]+", ...) on lowercased text; digits split words.
"""
import unicodedata
from typing import List

_CHANDRABINDU = "ँ"
_ANUSVARA = "ं"
_NUKTA = "़"

# Spelling variants -> the one form used in the word sets (applied after the mark rules above).
DEVANAGARI_SPELLINGS = {
    "नही": "नहीं",
    "नहि": "नहीं",
    "बिलकुल": "बिल्कुल",
    "कैंसिल": "कैंसल",
    "कैन्सल": "कैंसल",
    "कैन्सिल": "कैंसल",
    "ओकै": "ओके",
    "कनफर्म": "कन्फर्म",
    "कंफर्म": "कन्फर्म",
    "हांजि": "हांजी",
    "रद": "रद्द",
}


def _is_word_char(ch: str) -> bool:
    return unicodedata.category(ch)[0] in "LM"


def normalize_text(text: str) -> str:
    """NFC + lowercase + punctuation to spaces + Devanagari canonical forms; words joined by single spaces."""
    return " ".join(words(text))


def words(text: str) -> List[str]:
    s = unicodedata.normalize("NFC", text or "").lower()
    # NFC turns the precomposed nukta letters (क़ ज़ फ़ ...) into letter + nukta, so dropping the nukta covers both.
    s = s.replace(_CHANDRABINDU, _ANUSVARA).replace(_NUKTA, "")
    out: List[str] = []
    current: List[str] = []
    for ch in s:
        if _is_word_char(ch):
            current.append(ch)
        elif current:
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return [DEVANAGARI_SPELLINGS.get(w, w) for w in out]


def canon(word: str) -> str:
    """One word in the same canonical form as words() produces (for building word sets)."""
    found = words(word)
    return found[0] if len(found) == 1 else normalize_text(word)


def is_devanagari_letter(ch: str) -> bool:
    return "ऀ" <= ch <= "ॿ" and unicodedata.category(ch).startswith("L")
