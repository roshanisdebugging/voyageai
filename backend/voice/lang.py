"""
Which language a piece of text is in, for voice templates and the TTS voice (fixes-before-step4 item 8).

Whisper often tags Romanized Hinglish as "en", so the tag can't decide the voice. Instead: Devanagari, or
common Hindi words written in Roman letters -> "hi" (Sarvam hi-IN); plain English -> "en" (en-IN).
"""
import re
from typing import Optional

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_WORD = re.compile(r"[a-zA-Z]+")

# Frequent Hindi/Hinglish function words and verbs in Roman script. Words that are also common English
# words ("me", "to", "the", "is", "main" as in "main road") are left out on purpose.
HINGLISH_WORDS = {
    "hai", "hain", "ho", "hoga", "hogi", "hoge", "tha", "thi", "the_", "kya", "kyun", "kyon", "kaise", "kaisa", "kaisi",
    "kahan", "kidhar", "kab", "kitna", "kitne", "kitni", "kaun", "kaunsa", "kaunsi", "kaun si", "mein", "mujhe", "mera",
    "meri", "mere", "hum", "humein", "aap", "aapka", "aapki", "aapke", "aapko", "tum", "tumhara", "ka", "ki", "ke", "ko",
    "se", "par", "pe", "aur", "ya", "nahi", "nahin", "haan", "ha", "ji", "acha", "accha", "theek", "thik", "bhi",
    "kholo", "khol", "kholna", "dikhao", "dikha", "dikhaun", "dikhaiye", "batao", "bataiye", "bata", "chahiye",
    "chahte", "chahta", "chahti", "karo", "karna", "karni", "kar", "karein", "kijiye", "diya", "di", "diye", "gaya",
    "gayi", "raha", "rahi", "rahe", "wala", "wali", "wale", "abhi", "kal", "aaj", "parso", "jaana", "jana", "jaayein",
    "chalo", "chalein", "le", "lo", "sakta", "sakti", "sakte", "milega", "milegi", "nayi", "naya", "purani", "agli",
    "pichli", "trip", "baarish", "barish", "mausam", "garmi", "thand", "khana", "ghoomne", "jagah", "kuch", "sab",
    "phir", "samajh", "aaya", "boliye", "sirf", "madad", "lagta", "lagega", "zyada", "kam", "thoda", "bahut",
    "ek", "do_", "teen", "sunao", "suno", "bolo", "bataao", "dikhaiye", "chaliye", "jaayen", "jaaun", "jaun", "doosre",
    "teesre", "pehle", "din", "kharche", "ghoomna", "chahiye", "wahan", "yahan", "kitni", "kaisa", "hoon", "hu", "hun",
    "mat", "rehne", "lagao", "kahin", "koi", "sabse", "accha", "achha", "dikhado", "batado", "khulta", "khulti",
}
# "trip" is shared with English; it only counts together with another Hindi word (see below).
_SHARED = {"trip"}


def detect_lang(text: Optional[str], fallback: Optional[str] = None) -> str:
    """'hi' or 'en'. fallback (e.g. Whisper's tag) is used only when the text has no letters at all."""
    t = text or ""
    if _DEVANAGARI.search(t):
        return "hi"
    words = [w.lower() for w in _WORD.findall(t)]
    if not words:
        return "en" if (fallback or "").lower() == "en" else "hi"
    hits = [w for w in words if w in HINGLISH_WORDS]
    strong = [w for w in hits if w not in _SHARED]
    if strong:
        return "hi"
    return "en"


def sarvam_code(text: Optional[str], fallback: Optional[str] = None) -> str:
    return "hi-IN" if detect_lang(text, fallback) == "hi" else "en-IN"
