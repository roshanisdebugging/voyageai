"""
Checked trip plans ("cards") from backend/pilgrimage/*.json: loading, matching and the days rule.

- Loaded once (load_cards, called at server and worker start). Every file is validated; a bad file is logged and
  skipped, never stopping the server or the other cards. Logs hold the card id / file name and the reason only.
- Matching is plain code: the destination the user said, normalised (lowercase, trimmed, Devanagari spellings
  folded with voice.text_utils.canon), compared with each card's match_names. No match: the old flow runs.
- plan_days applies the days rule. Card content is never edited here; trips copy what they need.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger("pilgrimage")

CARDS_DIR = Path(__file__).resolve().parent / "pilgrimage"
MAX_DAYS = 30


# ---------------- format

class Stop(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    visit_minutes: int = Field(ge=1, le=24 * 60)
    priority: Literal["must", "optional"]
    note: Optional[str] = None


class CardDay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    day_number: int = Field(ge=1, le=MAX_DAYS)
    title: str = Field(min_length=1, max_length=200)
    stops: List[Stop] = Field(min_length=1)


class BookingNote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    official_url: Optional[str] = None

    @field_validator("official_url")
    @classmethod
    def _https(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not re.match(r"^https://[^\s]+$", v):
            raise ValueError("official_url must be an https link")
        return v


class AvoidMonths(BaseModel):
    model_config = ConfigDict(extra="forbid")
    months: List[int]
    reason: str

    @field_validator("months")
    @classmethod
    def _months(cls, v: List[int]) -> List[int]:
        if not v or any(m < 1 or m > 12 for m in v):
            raise ValueError("months must be 1-12")
        return v


class Card(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    version: int = Field(ge=1)
    status: str = Field(min_length=1, max_length=40)
    name_en: str = Field(min_length=1, max_length=120)
    name_hi: str = Field(min_length=1, max_length=120)
    match_names: List[str] = Field(min_length=1)
    region: str
    kind: str
    duration_days_min: int = Field(ge=1, le=MAX_DAYS)
    duration_days_max: int = Field(ge=1, le=MAX_DAYS)
    default_days: int = Field(ge=1, le=MAX_DAYS)
    best_months: List[int]
    avoid_months: List[AvoidMonths]
    days: List[CardDay] = Field(min_length=1)
    booking_notes: List[BookingNote]
    dress_code: Optional[str] = None
    elderly_notes: Optional[str] = None
    transport_notes: Optional[str] = None
    last_verified: Optional[date] = None
    sources: List[str]
    unverified: List[str]

    @field_validator("best_months")
    @classmethod
    def _best(cls, v: List[int]) -> List[int]:
        if any(m < 1 or m > 12 for m in v):
            raise ValueError("months must be 1-12")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> "Card":
        if [d.day_number for d in self.days] != list(range(1, len(self.days) + 1)):
            raise ValueError("days must be numbered 1, 2, 3 ... in order")
        if not self.duration_days_min <= self.default_days <= self.duration_days_max:
            raise ValueError("default_days must be between duration_days_min and duration_days_max")
        if not any(normalise(n) for n in self.match_names):
            raise ValueError("match_names has no usable name")
        return self

    @property
    def short_name(self) -> str:
        """'Kashi Yatra, Varanasi' -> 'Kashi Yatra' (what the voice question says)."""
        return self.name_en.split(",")[0].strip()


# ---------------- matching

def normalise(text: str) -> str:
    """Lowercase, trimmed, punctuation dropped, Devanagari spellings folded (हाँ == हां, nukta dropped)."""
    from voice.text_utils import canon, words
    return " ".join(canon(w) for w in words(str(text or "").lower()))


def _contains(haystack: str, needle: str) -> bool:
    return bool(needle) and f" {needle} " in f" {haystack} "


# ---------------- loading

@dataclass
class LoadResult:
    cards: Dict[str, Card] = field(default_factory=dict)
    rejected: Dict[str, str] = field(default_factory=dict)   # file name -> reason


_CARDS: Optional[Dict[str, Card]] = None


def _reason(err: Exception) -> str:
    """Short and content-free: where in the file and what kind of problem."""
    errors = getattr(err, "errors", None)
    if callable(errors):
        first = errors()[0] if errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", ()))
        return f"{first.get('type', 'invalid')} at {loc or 'top level'}"
    if isinstance(err, json.JSONDecodeError):
        return f"not valid JSON (line {err.lineno})"
    return type(err).__name__


def load_cards(folder: Optional[Path] = None) -> LoadResult:
    """Read every *.json in the folder. Never raises: a bad file is listed in `rejected` and skipped."""
    folder = Path(folder) if folder is not None else CARDS_DIR
    out = LoadResult()
    try:
        files = sorted(p for p in folder.glob("*.json") if p.is_file())
    except Exception as err:
        print(f"[PILGRIMAGE] cards folder not readable ({type(err).__name__}); no cards", flush=True)
        return out
    for path in files:
        try:
            card = Card.model_validate(json.loads(path.read_text(encoding="utf-8")))
            if card.id in out.cards:
                raise ValueError("duplicate id")
            out.cards[card.id] = card
            print(f"[PILGRIMAGE] card loaded id={card.id} status={card.status}", flush=True)
        except Exception as err:
            out.rejected[path.name] = _reason(err)
            print(f"[PILGRIMAGE] card rejected file={path.name} reason={out.rejected[path.name]}", flush=True)
    if not files:
        print("[PILGRIMAGE] no card files found", flush=True)
    return out


def init_cards(folder: Optional[Path] = None) -> Dict[str, Card]:
    """Load (or reload) the cards for this process. Called at server and worker start."""
    global _CARDS
    _CARDS = load_cards(folder).cards
    return _CARDS


def cards() -> Dict[str, Card]:
    global _CARDS
    if _CARDS is None:
        init_cards()
    return _CARDS or {}


def get_card(card_id: Optional[str]) -> Optional[Card]:
    return cards().get(str(card_id or ""))


def match_card(*said: Optional[str]) -> Optional[Card]:
    """The card whose match_names equal what the user said (any of the given texts), else None.
    A whole-word match inside a longer phrase also counts ("Varanasi trip"). First card wins on a tie."""
    texts = [normalise(s) for s in said if s]
    texts = [t for t in texts if t]
    if not texts:
        return None
    for card in cards().values():
        names = [normalise(n) for n in card.match_names]
        if any(t == n for t in texts for n in names if n):
            return card
    for card in cards().values():
        names = [normalise(n) for n in card.match_names]
        if any(_contains(t, n) for t in texts for n in names if n):
            return card
    return None


def card_fits_destination(card: Card, destination: Optional[dict]) -> bool:
    """Server check at trip creation: the trip's destination (name / city / displayName) still names this card's
    place. A destination changed on the review page to somewhere else drops the card."""
    d = destination or {}
    fields = [normalise(d.get(k) or "") for k in ("name", "city", "displayName")]
    names = [normalise(n) for n in card.match_names]
    return any(f and n and (f == n or _contains(f, n)) for f in fields for n in names)


# ---------------- days rule

@dataclass
class PlannedDay:
    title: str
    stops: List[Stop]
    card_day: int            # the card's day_number this came from


@dataclass
class DayPlan:
    card_days: List[PlannedDay]   # in order: trip days 1..len(card_days)
    extra_days: int               # trip days after them, for the AI (or free)


def plan_days(card: Card, total_days: Optional[int]) -> DayPlan:
    """
    The days rule (code, no AI):
    - no days: the card's default_days (callers pass None);
    - same as the card: the card exactly;
    - more: the card exactly, then `extra_days` for the AI;
    - fewer: days holding only optional stops are dropped (from the end) until it fits, then whole days are
      dropped from the end. Must stops are kept as long as their day is.
    """
    n = int(total_days) if total_days else card.default_days
    days = [PlannedDay(d.title, list(d.stops), d.day_number) for d in card.days]
    if n >= len(days):
        return DayPlan(days, n - len(days))
    # Fewer days: must stops first. A day of only optional stops is dropped (last such day first); dropping
    # optional stops from a day that also has must stops would not shorten the trip, so those stay.
    for i in range(len(days) - 1, -1, -1):
        if len(days) <= n:
            break
        if all(s.priority == "optional" for s in days[i].stops):
            days.pop(i)
    # Still too long: whole days from the end.
    return DayPlan(days[:n], 0)
