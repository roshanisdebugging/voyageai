"""
Bengali words the voice code listens for and says (feat/bengali, beta): numbers 0-100, months, day words, rupee
multipliers. Shared by voice/draft.py (dates, people, budget), voice/booking_voice.py (ages, rooms) and
voice/tools/lookups.py (weather day). Not reviewed by a native speaker yet: docs/bengali_review.md.

Matching is on whole words, after voice.text_utils.words() (NFC, lowercase, punctuation -> spaces), like the Hindi and
English lists. Bengali digits (০-৯) need nothing here: Python's int() and float() read them.
"""
from __future__ import annotations

import re
from typing import Dict, Optional

# 0..100 in the usual spoken (Kolkata standard) form.
BN_NUMBERS = [
    "শূন্য", "এক", "দুই", "তিন", "চার", "পাঁচ", "ছয়", "সাত", "আট", "নয়", "দশ",
    "এগারো", "বারো", "তেরো", "চোদ্দ", "পনেরো", "ষোলো", "সতেরো", "আঠারো", "উনিশ", "কুড়ি",
    "একুশ", "বাইশ", "তেইশ", "চব্বিশ", "পঁচিশ", "ছাব্বিশ", "সাতাশ", "আটাশ", "ঊনত্রিশ", "তিরিশ",
    "একত্রিশ", "বত্রিশ", "তেত্রিশ", "চৌত্রিশ", "পঁয়ত্রিশ", "ছত্রিশ", "সাঁইত্রিশ", "আটত্রিশ", "ঊনচল্লিশ", "চল্লিশ",
    "একচল্লিশ", "বিয়াল্লিশ", "তেতাল্লিশ", "চুয়াল্লিশ", "পঁয়তাল্লিশ", "ছেচল্লিশ", "সাতচল্লিশ", "আটচল্লিশ", "ঊনপঞ্চাশ", "পঞ্চাশ",
    "একান্ন", "বাহান্ন", "তিপ্পান্ন", "চুয়ান্ন", "পঞ্চান্ন", "ছাপ্পান্ন", "সাতান্ন", "আটান্ন", "ঊনষাট", "ষাট",
    "একষট্টি", "বাষট্টি", "তেষট্টি", "চৌষট্টি", "পঁয়ষট্টি", "ছেষট্টি", "সাতষট্টি", "আটষট্টি", "ঊনসত্তর", "সত্তর",
    "একাত্তর", "বাহাত্তর", "তিয়াত্তর", "চুয়াত্তর", "পঁচাত্তর", "ছিয়াত্তর", "সাতাত্তর", "আটাত্তর", "ঊনআশি", "আশি",
    "একাশি", "বিরাশি", "তিরাশি", "চুরাশি", "পঁচাশি", "ছিয়াশি", "সাতাশি", "অষ্টাশি", "ঊননব্বই", "নব্বই",
    "একানব্বই", "বিরানব্বই", "তিরানব্বই", "চুরানব্বই", "পঁচানব্বই", "ছিয়ানব্বই", "সাতানব্বই", "আটানব্বই", "নিরানব্বই", "একশো",
]
# Other common spellings / forms of the same numbers (speech-to-text writes either).
BN_NUMBER_VARIANTS = {
    "দু": 2, "দুটো": 2, "দুটি": 2, "একটা": 1, "একটি": 1, "তিনটে": 3, "তিনটি": 3, "চারটে": 4, "চারটি": 4,
    "পাঁচটা": 5, "পাঁচটি": 5, "ছ": 6, "ছটা": 6, "চৌদ্দ": 14, "বিশ": 20, "ত্রিশ": 30, "উনত্রিশ": 29,
    "একশ": 100, "একশত": 100, "শো": 100, "শ": 100,
}
BN_ZERO_ANSWERS = ("কেউ না", "কেউ নেই", "নেই", "না", "কোনো বাচ্চা নেই", "বাচ্চা নেই", "কেউ যাচ্ছে না")

BN_MONTHS = ["জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন", "জুলাই", "আগস্ট", "সেপ্টেম্বর", "অক্টোবর",
             "নভেম্বর", "ডিসেম্বর"]
BN_MONTH_VARIANTS = {"জানুয়ারী": 1, "ফেব্রুয়ারী": 2, "আগষ্ট": 8, "সেপ্টেমবর": 9, "অক্টোবার": 10, "নভেম্বার": 11,
                     "ডিসেম্বার": 12}
# "aaj / kal / parso" in Bengali: 0 = today, 1 = tomorrow, 2 = the day after.
BN_DAY_WORDS = {"আজ": 0, "আজকে": 0, "কাল": 1, "কালকে": 1, "আগামীকাল": 1, "পরশু": 2, "পরশুদিন": 2}
BN_MULTIPLIERS = {"হাজার": 1000, "লাখ": 100_000, "লক্ষ": 100_000, "কোটি": 10_000_000}


def _w(text: str):
    from voice.text_utils import words
    return words(text)


def _table(items) -> Dict[str, int]:
    from voice.text_utils import canon
    return {canon(w): n for w, n in items}


_NUM: Optional[Dict[str, int]] = None
_MON: Optional[Dict[str, int]] = None


def _numbers() -> Dict[str, int]:
    global _NUM
    if _NUM is None:
        _NUM = _table([(w, i) for i, w in enumerate(BN_NUMBERS)] + list(BN_NUMBER_VARIANTS.items()))
    return _NUM


def _months() -> Dict[str, int]:
    global _MON
    if _MON is None:
        _MON = _table([(m, i + 1) for i, m in enumerate(BN_MONTHS)] + list(BN_MONTH_VARIANTS.items()))
    return _MON


def number(text) -> Optional[int]:
    """One Bengali number word ("পঁচিশ" -> 25, "দুটো" -> 2), or None. A zero answer ("কেউ নেই") -> 0."""
    if text is None:
        return None
    raw = " ".join(_w(str(text)))
    if raw in {" ".join(_w(z)) for z in BN_ZERO_ANSWERS}:
        return 0
    ws = raw.split()
    return _numbers().get(ws[0]) if len(ws) == 1 else None


def first_number(words_list) -> Optional[int]:
    """The first Bengali number word in a list of words (already words()-normalised), or None."""
    table = _numbers()
    return next((table[w] for w in words_list if w in table), None)


def month(text) -> Optional[int]:
    """A Bengali month name -> 1..12, or None."""
    ws = _w(str(text or ""))
    return _months().get(ws[0]) if len(ws) == 1 else None


def day_offset(text) -> Optional[int]:
    """আজ / কাল / পরশু -> 0 / 1 / 2, or None."""
    ws = _w(str(text or ""))
    return BN_DAY_WORDS.get(ws[0]) if len(ws) == 1 else None


def budget(text) -> Optional[int]:
    """"৫০ হাজার" / "50 হাজার" / "পঞ্চাশ হাজার" / "1.5 লাখ" -> rupees; None if it isn't one of these."""
    s = str(text or "").replace(",", "").replace("₹", "").replace("টাকা", "").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(\S+)?", s)
    if m:
        mult = BN_MULTIPLIERS.get(m.group(2) or "", 1 if not m.group(2) else None)
        return int(round(float(m.group(1)) * mult)) if mult else None
    ws = _w(s)
    if len(ws) == 2 and ws[0] in _numbers() and ws[1] in BN_MULTIPLIERS:
        return _numbers()[ws[0]] * BN_MULTIPLIERS[ws[1]]
    return None
