"""
Voice step 5: actions on the open trip (voicefirst.md "Step 5 in detail: more actions").

Small (run now, with an Undo toast): mark_activity_done, save_place, unsave_place.
Big (a pending confirmation; run only on "haan" or the Confirm button): add_expense, regenerate_itinerary.
swap_activity opens the existing swap sheet; the sheet's own Confirm applies the swap.
Voice never deletes.

Which trip: the one the user named ("Goa wali trip mein..."), matched by code exactly like open_trip
(name, month, next/current/last); otherwise the trip open in the app; otherwise ask "Kaun si trip mein?" and do
nothing. A pending big action carries its trip_id; on confirm the trip is re-checked (still the user's, still the
same trip as when it was asked).

Rules: the trip comes from voice/context.py (ownership-checked); activities are matched by CODE against that
trip's own activities; every write goes through trip_actions.py (which checks ownership again).
The model's words never become IDs. Logs carry action names only (voice/agent.py logs them).
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from voice import context as C
from voice.languages import AND_WORD, OR_WORD, tkey  # noqa: F401

LAST_PLACE_TTL_SECONDS = 30 * 60
PLACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,300}$")

# The ONLY /ws/app actions an Undo may run (the frontend has the same allowlist).
UNDO_ALLOWLIST = {"trips:set_activity_done", "places:save", "places:unsave"}

# Voice category -> the app's expense category (frontend TripExpense.category).
EXPENSE_CATEGORY = {"food": "Food", "transport": "Transport", "stay": "Hotel", "shopping": "Shopping",
                    "tickets": "Activities", "other": "Other"}
CATEGORY_WORD = {
    "hi": {"food": "khane", "transport": "transport", "stay": "stay", "shopping": "shopping", "tickets": "tickets", "other": "other"},
    "en": {"food": "food", "transport": "transport", "stay": "stay", "shopping": "shopping", "tickets": "tickets", "other": "other"},
    "bn": {'food': "খাবার",
           'transport': "যাতায়াত",
           'stay': "থাকা",
           'shopping': "কেনাকাটা",
           'tickets': "টিকিট",
           'other': "অন্যান্য"},
}
MAX_EXPENSE = 1_000_000
REGEN_RATE = ("ai_trip", 10)   # same bucket and limit as WS_RATE_LIMITS["trips:regenerate_itinerary"] in main.py

T = {
    "no_trip": {"hi": "Kaun si trip mein?", "en": "Which trip?", "bn": "কোন ট্রিপে?"},
    "trip_changed": {"hi": "Ab doosri trip khuli hai, isliye kuch nahi badla. Phir se boliye.",
                     "en": "A different trip is open now, so nothing changed. Please say it again.", "bn": "এখন অন্য একটা ট্রিপ খোলা আছে, তাই কিছু বদলানো হয়নি। আবার বলুন।"},
    "no_itinerary": {"hi": "Is trip ka itinerary abhi tayyar nahi hai.", "en": "This trip's itinerary isn't ready yet.", "bn": "এই ট্রিপের ইটিনেরারি এখনো তৈরি হয়নি।"},
    "which_activity": {"hi": "Kaunsi activity? Yeh naam itinerary mein nahi mila.", "en": "Which activity? I couldn't find that name in the itinerary.", "bn": "কোন অ্যাক্টিভিটি? এই নামটা ইটিনেরারিতে পেলাম না।"},
    "no_activity_named": {"hi": "Kaunsi activity?", "en": "Which activity?", "bn": "কোন অ্যাক্টিভিটি?"},
    "no_place": {"hi": "Kaunsi jagah? Pehle jagah dhoondhiye ya kholiye, phir save boliye.",
                 "en": "Which place? Search for it or open it first, then say save.", "bn": "কোন জায়গা? আগে জায়গাটা খুঁজুন বা খুলুন, তারপর সেভ বলুন।"},
    "not_saved": {"hi": "Yeh jagah saved nahi hai.", "en": "That place isn't saved.", "bn": "এই জায়গাটা সেভ করা নেই।"},
    "bad_amount": {"hi": "Kitne rupaye ka kharcha tha?", "en": "How much was it, in rupees?", "bn": "কত টাকা খরচ হয়েছিল?"},
    "regen_ask": {"hi": "Poora itinerary dobara banaun? Isme thoda time lagega.",
                  "en": "Rebuild the whole itinerary? It will take a little time.", "bn": "পুরো ইটিনেরারি আবার বানাব? একটু সময় লাগবে।"},
    "regen_busy": {"hi": "Itinerary pehle se ban raha hai, thodi der rukiye.", "en": "The itinerary is already being rebuilt, please wait.", "bn": "ইটিনেরারি আগে থেকেই তৈরি হচ্ছে, একটু অপেক্ষা করুন।"},
    "regen_done": {"hi": "Itinerary dobara ban raha hai. Ready hone par bata dunga.", "en": "Rebuilding the itinerary. I'll tell you when it's ready.", "bn": "ইটিনেরারি আবার বানাচ্ছি। তৈরি হলে জানিয়ে দেব।"},
    "rate_limited": {"hi": "Abhi bahut requests ho gayi, thodi der baad boliye.", "en": "Too many requests right now, please try again in a bit.", "bn": "এখন অনেক বেশি অনুরোধ এসেছে, একটু পরে আবার বলুন।"},
    "failed": {"hi": "Abhi yeh nahi ho paaya, phir se koshish kariye.", "en": "That didn't work, please try again.", "bn": "এটা হলো না, আবার চেষ্টা করুন।"},
    "gone": {"hi": "Yeh trip ab nahi mili, kuch nahi badla.", "en": "That trip isn't available any more; nothing changed.", "bn": "এই ট্রিপটা আর পাওয়া যাচ্ছে না, কিছু বদলানো হয়নি।"},
}


def _res(text: str, **kw):
    from voice.agent import AgentResult
    return AgentResult(text, **kw)


def undo_toast(message: str, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """An Undo toast ui_action. Only allowlisted /ws/app actions; anything else is refused here."""
    if action not in UNDO_ALLOWLIST:
        raise ValueError("undo action not allowed")
    return {"type": "undo_toast", "message": message[:120], "undo": {"action": action, "payload": payload}}


def _db():
    import database
    return database.SessionLocal()


# "Which one: Amber Fort (day 1) or City Palace (day 2)?"
DAY_TAG = {"hi": "{title} (din {n})", "en": "{title} (day {n})", "bn": "{title} ({n} নম্বর দিন)"}
ASK_WHICH = {"hi": "Kaunsa: {names}?", "en": "Which one: {names}?", "bn": "কোনটা: {names}?"}


def _ask_which(cands: List[C.Act], lang: str):
    if not cands:
        return _res(T["which_activity"][lang], action="ask_activity", error_code="unknown_activity")
    k = tkey(lang)
    names = OR_WORD[k].join(DAY_TAG[k].format(title=a.title, n=a.day_number) for a in cands[:3])
    return _res(ASK_WHICH[k].format(names=names), action="ask_activity", error_code="ambiguous_activity")


# ---------------- which trip

def _named(args: Dict[str, Any]) -> bool:
    return any(isinstance(args.get(k), str) and args.get(k).strip() for k in ("trip_name", "trip_month", "trip_which"))


def resolve_trip(user_id: str, open_ctx: Optional[C.TripContext], args: Dict[str, Any], lang: str):
    """
    (ctx, named_other, None) or (None, False, AgentResult asking). named_other = the user named a trip that isn't
    the open one (replies then say the trip's name). Matching is code (lookups.match_trips), the user's own trips only.
    """
    if _named(args):
        from voice.tools import lookups
        try:
            _all, cands = lookups.match_trips(user_id, args.get("trip_name"), args.get("trip_month"), args.get("trip_which"))
        except Exception as err:
            return None, False, _res(T["failed"][lang], action="ask_trip", error_code=type(err).__name__)
        if not cands:
            return None, False, _res(lookups.NO_SUCH_TRIP[lang], action="ask_trip", error_code="trip_not_found")
        if len(cands) > 1:
            return None, False, _res(lookups.which_trip_question(cands, lang), action="ask_trip", error_code="ambiguous_trip")
        if open_ctx is not None and cands[0].id == open_ctx.trip_id:
            return open_ctx, False, None
        ctx = C.load(user_id, cands[0].id)
        if ctx is None:
            return None, False, _res(lookups.NO_SUCH_TRIP[lang], action="ask_trip", error_code="trip_not_found")
        return ctx, True, None
    if open_ctx is not None:
        return open_ctx, False, None
    return None, False, _res(T["no_trip"][lang], action="ask_trip", error_code="no_trip")


def trip_label(ctx: C.TripContext) -> str:
    return ((ctx.destination or ctx.title or "Trip").split(",")[0].strip())[:40]


def _need_activity(ctx: Optional[C.TripContext], name: Any, lang: str):
    """(act, None) or (None, AgentResult asking a question)."""
    if not ctx.activities:
        return None, _res(T["no_itinerary"][lang], action="ask_activity", error_code="no_itinerary")
    if not isinstance(name, str) or not name.strip():
        return None, _res(T["no_activity_named"][lang], action="ask_activity", error_code="no_activity_named")
    act, cands = C.match_activity(ctx, name)
    if act is None:
        return None, _ask_which(cands, lang)
    return act, None


# ---------------- small: mark done

def mark_activity_done(user_id: str, open_ctx: Optional[C.TripContext], args: Dict[str, Any], lang: str):
    import trip_actions
    ctx, other, ask = resolve_trip(user_id, open_ctx, args, lang)
    if ask:
        return ask
    act, ask = _need_activity(ctx, args.get("activity"), lang)
    if ask:
        return ask
    done = args.get("done") is not False
    try:
        with _db() as db:
            trip_actions.set_activity_done(db, user_id, ctx.trip_id, act.id, done)
    except LookupError:
        return _res(T["gone"][lang], action="mark_done", error_code="not_owned")
    except Exception as err:
        return _res(T["failed"][lang], action="mark_done", error_code=type(err).__name__)
    where = {"hi": f"{trip_label(ctx)} trip mein ", "en": f"In your {trip_label(ctx)} trip, ", "bn": f"আপনার {trip_label(ctx)} ট্রিপে, "}[lang] if other else ""
    if done:
        text = {"hi": f"{where}{act.title} done mark kar diya.", "en": f"{where}marked {act.title} as done.", "bn": f"{where}{act.title} হয়ে গেছে বলে চিহ্নিত করলাম।"}[lang]
    else:
        text = {"hi": f"{where}{act.title} se done hata diya.", "en": f"{where}{act.title} is no longer marked done.", "bn": f"{where}{act.title} থেকে 'হয়ে গেছে' চিহ্ন সরিয়ে দিলাম।"}[lang]
    text = text[0].upper() + text[1:]
    toast = undo_toast(text, "trips:set_activity_done", {"trip_id": ctx.trip_id, "activity_id": act.id, "done": not done})
    return _res(text, action="mark_done", ui_actions=[{"type": "refresh", "what": "itinerary"}, toast])


# ---------------- small: save / unsave a place

def _last_place_key(user_id: str, conversation_id: str) -> str:
    return f"voice:lastplace:{user_id}:{conversation_id}"


def remember_place(redis_conn, user_id: str, conversation_id: str, place: Optional[Dict[str, Any]]) -> None:
    """The last search_places result (so "yeh jagah save karo" knows the place)."""
    if not place or not PLACE_ID_RE.match(str(place.get("place_id") or "")):
        return
    try:
        redis_conn.setex(_last_place_key(user_id, conversation_id), LAST_PLACE_TTL_SECONDS, json.dumps({
            "place_id": place["place_id"], "name": str(place.get("name") or "")[:120],
            "address": str(place.get("address") or "")[:200]}))
    except Exception:
        pass


def forget_place(redis_conn, user_id: str, conversation_id: str) -> None:
    """After a list of places (search_nearby) there is no single "this place" any more."""
    try:
        redis_conn.delete(_last_place_key(user_id, conversation_id))
    except Exception:
        pass


def _last_place(redis_conn, user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
    try:
        raw = redis_conn.get(_last_place_key(user_id, conversation_id))
        return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw) if raw else None
    except Exception:
        return None


def _same_name(a: str, b: str) -> bool:
    ta, tb = set(C._tokens(a)), set(C._tokens(b))
    return bool(ta and tb) and (ta <= tb or tb <= ta or len(ta & tb) / max(1, min(len(ta), len(tb))) >= 0.6)


def _target_place(redis_conn, user_id, conversation_id, screen_place, spoken: Any) -> Optional[Dict[str, Any]]:
    """The place on screen, else the last searched one; if the user named a place, it must be that one."""
    options = [p for p in (screen_place, _last_place(redis_conn, user_id, conversation_id))
               if p and PLACE_ID_RE.match(str(p.get("place_id") or "")) and p.get("name")]
    if isinstance(spoken, str) and spoken.strip() and not re.fullmatch(r"\s*(yeh|ye|this|is|iss|wo|woh)?\s*(jagah|place)?\s*", spoken.lower()):
        options = [p for p in options if _same_name(spoken, p["name"])]
    return options[0] if options else None


def save_place(redis_conn, user_id: str, conversation_id: str, screen_place, args: Dict[str, Any], lang: str):
    import trip_actions
    place = _target_place(redis_conn, user_id, conversation_id, screen_place, args.get("place"))
    if not place:
        return _res(T["no_place"][lang], action="ask_place", error_code="no_place")
    name = place["name"]
    try:
        with _db() as db:
            if trip_actions.find_saved_place(db, user_id, place["place_id"]) is not None:
                return _res({"hi": f"{name} pehle se saved hai.", "en": f"{name} is already saved.", "bn": f"{name} আগে থেকেই সেভ করা আছে।"}[lang], action="save_place")
            trip_actions.save_place(db, user_id, place_id=place["place_id"], title=name,
                                    location_name=place.get("address") or "")
    except Exception as err:
        return _res(T["failed"][lang], action="save_place", error_code=type(err).__name__)
    text = {"hi": f"{name} save kar diya.", "en": f"Saved {name}.", "bn": f"{name} সেভ করে দিলাম।"}[lang]
    toast = undo_toast(text, "places:unsave", {"place_id": place["place_id"]})
    return _res(text, action="save_place", ui_actions=[{"type": "refresh", "what": "saved_places"}, toast])


def unsave_place(redis_conn, user_id: str, conversation_id: str, screen_place, args: Dict[str, Any], lang: str):
    import trip_actions
    from models_db import SavedPlaceModel
    spoken = args.get("place")
    try:
        with _db() as db:
            row = None
            target = _target_place(redis_conn, user_id, conversation_id, screen_place, spoken)
            if target:
                row = trip_actions.find_saved_place(db, user_id, target["place_id"])
            if row is None and isinstance(spoken, str) and spoken.strip():
                # Match the spoken name against the user's OWN saved places (code, not the model).
                mine = db.query(SavedPlaceModel).filter(SavedPlaceModel.user_id == user_id).all()
                hits = [r for r in mine if _same_name(spoken, r.title or "")]
                if len(hits) > 1:
                    names = OR_WORD[tkey(lang)].join(h.title for h in hits[:3])
                    return _res({"hi": f"Kaunsi: {names}?", "en": f"Which one: {names}?", "bn": f"কোনটা: {names}?"}[lang], action="ask_place",
                                error_code="ambiguous_place")
                row = hits[0] if hits else None
            if row is None:
                return _res(T["not_saved"][lang] if (target or spoken) else T["no_place"][lang], action="ask_place",
                            error_code="not_saved")
            name = row.title
            res = trip_actions.unsave_place(db, user_id, row.place_id)
    except Exception as err:
        return _res(T["failed"][lang], action="unsave_place", error_code=type(err).__name__)
    text = {"hi": f"{name} saved se hata diya.", "en": f"Removed {name} from saved places.", "bn": f"{name} সেভ করা জায়গা থেকে সরিয়ে দিলাম।"}[lang]
    removed = res.get("removed") or {"place_id": res["place_id"], "title": name}
    payload = {k: v for k, v in removed.items() if v is not None}
    toast = undo_toast(text, "places:save", payload)
    return _res(text, action="unsave_place", ui_actions=[{"type": "refresh", "what": "saved_places"}, toast])


# ---------------- big: add expense (pending until "haan" / Confirm)

def _amount(raw: Any) -> Optional[int]:
    from voice.draft import parse_budget
    try:
        v = parse_budget(raw)
    except Exception:
        v = None
    return v if v is not None and 1 <= v <= MAX_EXPENSE else None


def add_expense(redis_conn, user_id: str, conversation_id: str, open_ctx: Optional[C.TripContext], args: Dict[str, Any], lang: str):
    from voice import pending as P
    ctx, other, ask = resolve_trip(user_id, open_ctx, args, lang)
    if ask:
        return ask
    amount = _amount(args.get("amount"))
    if amount is None:
        return _res(T["bad_amount"][lang], action="ask_amount", error_code="bad_amount")
    cat = str(args.get("category") or "other").strip().lower()
    cat = cat if cat in EXPENSE_CATEGORY else "other"
    title = re.sub(r"\s+", " ", str(args.get("title") or "")).strip()[:60] or EXPENSE_CATEGORY[cat]
    word = CATEGORY_WORD[lang][cat]
    if other:   # not the open trip: the confirm line names it
        summary = {"hi": f"{trip_label(ctx)} trip mein ₹{amount:,}, {title}, {word} add karun?",
                   "en": f"Add ₹{amount:,} for {title} under {word} to your {trip_label(ctx)} trip?", "bn": f"আপনার {trip_label(ctx)} ট্রিপে {word} খাতে {title}-এর জন্য ₹{amount:,} যোগ করব?"}[lang]
    else:
        summary = {"hi": f"₹{amount:,}, {title}, {word} mein add karun?",
                   "en": f"Add ₹{amount:,} for {title} under {word}?", "bn": f"{word} খাতে {title}-এর জন্য ₹{amount:,} যোগ করব?"}[lang]
    pc = P.save(redis_conn, user_id, conversation_id, "add_expense", summary,
                {"trip_id": ctx.trip_id, "named": other, "title": title, "amount": amount, "category": cat})
    return _res(summary, action="expense_pending",
                pending_confirmation={"id": pc["id"], "summary": pc["summary"], "title": "Add this expense?"})


def same_trip(data: Dict[str, Any], open_trip_id: Optional[str]) -> bool:
    """
    On confirm: the pending trip must still be the one meant. A trip the user NAMED stays valid; a pending made for
    the open trip is refused if the app has since opened a different trip. (Ownership is re-checked by trip_actions.)
    """
    if data.get("named") or open_trip_id is None:
        return True
    return C.same_trip_id(open_trip_id, str(data.get("trip_id") or ""))


def run_add_expense(user_id: str, data: Dict[str, Any], lang: str, open_trip_id: Optional[str] = None):
    """On confirm only. The trip is re-checked (trip_actions) at run time."""
    import trip_actions
    if not same_trip(data, open_trip_id):
        return _res(T["trip_changed"][lang], action="expense_failed", error_code="trip_changed")
    cat = data.get("category") if data.get("category") in EXPENSE_CATEGORY else "other"
    amount = _amount(data.get("amount"))
    if amount is None:
        return _res(T["failed"][lang], action="expense_failed", error_code="bad_amount")
    try:
        with _db() as db:
            trip_actions.add_expense(db, user_id, str(data.get("trip_id") or ""), title=str(data.get("title") or "")[:60],
                                     amount=amount, category=EXPENSE_CATEGORY[cat])
    except LookupError:
        return _res(T["gone"][lang], action="expense_failed", error_code="not_owned")
    except Exception as err:
        return _res(T["failed"][lang], action="expense_failed", error_code=type(err).__name__)
    word = CATEGORY_WORD[lang][cat]
    text = {"hi": f"₹{amount:,} {word} mein add kar diya.", "en": f"Added ₹{amount:,} under {word}.", "bn": f"{word} খাতে ₹{amount:,} যোগ করে দিলাম।"}[lang]
    return _res(text, action="expense_added", ui_actions=[{"type": "refresh", "what": "expenses"}])


# ---------------- big: swap (the swap sheet's own Confirm applies it)

def swap_activity(user_id: str, open_ctx: Optional[C.TripContext], args: Dict[str, Any], lang: str):
    ctx, _other, ask = resolve_trip(user_id, open_ctx, args, lang)
    if ask:
        return ask
    act, ask = _need_activity(ctx, args.get("activity"), lang)
    if ask:
        return ask
    text = {"hi": f"{act.title} ki jagah options dikha raha hoon. Pasand ka chuniye.",
            "en": f"Here are options instead of {act.title}. Pick one.", "bn": f"{act.title}-এর বদলে কয়েকটা বিকল্প দেখাচ্ছি। পছন্দেরটা বেছে নিন।"}[lang]
    return _res(text, action="swap_open", ui_actions=[{"type": "open_swap", "trip_id": ctx.trip_id, "activity_id": act.id,
                                                       "activity_name": act.title, "day_number": act.day_number}])


# ---------------- big: regenerate (pending until "haan" / Confirm)

def regenerate_itinerary(redis_conn, user_id: str, conversation_id: str, open_ctx: Optional[C.TripContext],
                         args: Dict[str, Any], lang: str):
    from voice import pending as P
    ctx, other, ask = resolve_trip(user_id, open_ctx, args, lang)
    if ask:
        return ask
    if ctx.itinerary_status == "GENERATING":
        return _res(T["regen_busy"][lang], action="regen_busy")
    if other:
        summary = {"hi": f"{trip_label(ctx)} trip ka poora itinerary dobara banaun? Isme thoda time lagega.",
                   "en": f"Rebuild your {trip_label(ctx)} trip's whole itinerary? It will take a little time.", "bn": f"আপনার {trip_label(ctx)} ট্রিপের পুরো ইটিনেরারি আবার বানাব? একটু সময় লাগবে।"}[lang]
    else:
        summary = T["regen_ask"][lang]
    pc = P.save(redis_conn, user_id, conversation_id, "regenerate_itinerary", summary,
                {"trip_id": ctx.trip_id, "named": other})
    return _res(summary, action="regen_pending",
                pending_confirmation={"id": pc["id"], "summary": pc["summary"], "title": "Rebuild the itinerary?"})


def run_regenerate(redis_conn, user_id: str, data: Dict[str, Any], lang: str, open_trip_id: Optional[str] = None):
    """On confirm only: same trip, the AI rate-limit bucket (fails closed), then the shared action."""
    import trip_actions
    from rate_limiter import check_ws_rate_limit_sync
    if not same_trip(data, open_trip_id):
        return _res(T["trip_changed"][lang], action="regen_failed", error_code="trip_changed")
    try:
        wait = check_ws_rate_limit_sync(redis_conn, REGEN_RATE[0], user_id, REGEN_RATE[1])
    except Exception:
        return _res(T["failed"][lang], action="regen_failed", error_code="rate_limit_unavailable")
    if wait is not None:
        return _res(T["rate_limited"][lang], action="regen_failed", error_code="rate_limited")
    try:
        with _db() as db:
            trip_actions.regenerate_itinerary(db, user_id, str(data.get("trip_id") or ""))
    except LookupError:
        return _res(T["gone"][lang], action="regen_failed", error_code="not_owned")
    except Exception as err:
        return _res(T["failed"][lang], action="regen_failed", error_code=type(err).__name__)
    return _res(T["regen_done"][lang], action="regen_queued", ui_actions=[{"type": "refresh", "what": "itinerary"}])
