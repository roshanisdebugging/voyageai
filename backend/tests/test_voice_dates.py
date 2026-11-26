"""
Dates as spoken in voice trip creation: a day with no month ("पच्चीस तारीख") is the NEXT such day, never refused as
past. The model passes only the parts the user said (start_day / start_month / start_year ...); code picks the rest.
"Today" is injected (Asia/Kolkata dates), so nothing depends on the real date.
Run from backend/: python -m tests.test_voice_dates
No model or Google call: the model is a fake returning the fields it would extract; the place search is a fake.
"""
import contextlib
import io
import os
import sys
import uuid
from datetime import date
from pathlib import Path
from unittest import mock

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"
os.environ["OPENAI_API_KEY"] = "test-key-not-real"
os.environ["VOICE_TTS_ENABLED"] = "false"
os.environ.pop("VOICE_DEBUG_STORE", None)

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

import openai_client  # noqa: E402
import places  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from voice import agent, draft as D, pending as P  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if (detail != "" and not cond) else ""), flush=True)


R = D.resolve_said_date
N27, N10, D27, J27 = date(2026, 11, 27), date(2026, 11, 10), date(2026, 12, 27), date(2026, 1, 27)

# ---------------------------------------------------------------- the rule (pure)
check("today 27 Nov: '25 tarikh' -> 25 Dec 2026", R(25, None, None, N27) == date(2026, 12, 25))
check("today 27 Nov: '27 tarikh' -> 27 Nov 2026 (today is not past)", R(27, None, None, N27) == date(2026, 11, 27))
check("today 27 Nov: '5 tarikh' -> 5 Dec 2026", R(5, None, None, N27) == date(2026, 12, 5))
check("today 27 Nov: '5 November' -> 5 Nov 2027", R(5, 11, None, N27) == date(2027, 11, 5))
check("today 27 Nov: '27 November' -> today", R(27, 11, None, N27) == N27)
check("today 27 Nov: '15 January' -> 15 Jan 2027", R(15, 1, None, N27) == date(2027, 1, 15))
check("today 10 Nov: '25 tarikh' -> 25 Nov 2026", R(25, None, None, N10) == date(2026, 11, 25))
check("today 27 Dec: '5 tarikh' -> 5 Jan 2027 (year rollover)", R(5, None, None, D27) == date(2027, 1, 5))
check("today 27 Jan: '30 tarikh' -> 30 Jan (today's month still has it)", R(30, None, None, J27) == date(2026, 1, 30))
check("today 31 Jan: '30 tarikh' -> 30 March, never 30 Feb", R(30, None, None, date(2026, 1, 31)) == date(2026, 3, 30))
check("today 1 Feb: '31 tarikh' -> 31 March (February has no 31st)",
      R(31, None, None, date(2026, 2, 1)) == date(2026, 3, 31))
check("today 1 Apr: '31 tarikh' -> 31 May (April has no 31st)", R(31, None, None, date(2026, 4, 1)) == date(2026, 5, 31))
check("'29 February', no year -> the next leap year", R(29, 2, None, N27) == date(2028, 2, 29))
check("explicit year kept as said (past)", R(25, 11, 2025, N27) == date(2025, 11, 25))
check("explicit year kept as said (future)", R(25, 12, 2026, N27) == date(2026, 12, 25))
check("day 32 / month 13 / 30 Feb with a year -> None", R(32, None, None, N27) is None and R(5, 13, None, N27) is None
      and R(30, 2, 2027, N27) is None)

# ---------------------------------------------------------------- apply_update (as the draft does it)


def upd(args, today=N27, draft=None, lang="hi"):
    return D.apply_update(draft or D.TripDraftState(), args, lang, today, lambda q: None)


r = upd({"start_day": 25})
check("apply: start_day=25 (no month) -> 2026-12-25, not refused", not r.problems and r.draft.start_date == "2026-12-25" and r.date_rolled_forward,
      (r.problems, r.draft.start_date))
r = upd({"start_day": 25, "end_day": 27})
check("apply: '25 se 27' -> 25 to 27 Dec 2026", (r.draft.start_date, r.draft.end_date) == ("2026-12-25", "2026-12-27") and not r.problems,
      (r.draft.start_date, r.draft.end_date, r.problems))
r = upd({"start_day": 28, "end_day": 2})
check("apply: '28 se 2' -> 28 Nov to 2 Dec (end in the next month)", (r.draft.start_date, r.draft.end_date) == ("2026-11-28", "2026-12-02"),
      (r.draft.start_date, r.draft.end_date))
r = upd({"start_day": 30, "end_day": 2}, today=date(2026, 12, 10))
check("apply: '30 se 2' in December -> 30 Dec 2026 to 2 Jan 2027", (r.draft.start_date, r.draft.end_date) == ("2026-12-30", "2027-01-02"),
      (r.draft.start_date, r.draft.end_date))
r = upd({"start_day": 25, "start_month": 12, "end_day": 27})
check("apply: '25 December se 27' -> 25-27 Dec", (r.draft.start_date, r.draft.end_date) == ("2026-12-25", "2026-12-27"))
r = upd({"start_day": 25, "start_month": 12, "end_day": 2, "end_month": 1})
check("apply: '25 December se 2 January' -> into 2027", (r.draft.start_date, r.draft.end_date) == ("2026-12-25", "2027-01-02"))
r = upd({"start_day": 25, "days": 3})
check("apply: '25 tarikh se, 3 din' -> 25-27 Dec", (r.draft.start_date, r.draft.end_date) == ("2026-12-25", "2026-12-27"), r.problems)
r = upd({"start_day": 27})
check("apply: '27 tarikh' today -> today, not rolled", r.draft.start_date == "2026-11-27" and not r.date_rolled_forward)
r = upd({"start_day": 5, "start_month": 11})
check("apply: '5 November' -> 2027-11-05 (within the one-year limit)", r.draft.start_date == "2027-11-05" and not r.problems, r.problems)
r = upd({"start_day": 25, "start_month": 11, "start_year": 2025})
check("apply: '25 November 2025' -> refused as past (as before)", r.problems == ["Yeh tareekh beet chuki hai, aage ki tareekh boliye."]
      and r.draft.start_date is None, r.problems)
r = upd({"start_day": 25, "start_month": 11, "start_year": 2025}, lang="en")
check("apply: '25 November 2025' (en) -> refused", r.problems == ["That date has passed. Please say a future date."])
r = upd({"start_day": 25, "start_month": 12, "start_year": 2027})
check("apply: a year too far -> the one-year limit refusal (as before)", r.problems == ["Ek saal se aage ki trip abhi nahi ban sakti."], r.problems)
r = upd({"start_day": 40})
check("apply: day 40 -> 'Tareekh samajh nahi aayi.'", r.problems == ["Tareekh samajh nahi aayi."] and r.draft.start_date is None, r.problems)
r = upd({"start_date": "2026-11-25"})
check("apply: model sent only a past ISO date -> refused as before, fields flagged missing",
      r.problems == ["Yeh tareekh beet chuki hai, aage ki tareekh boliye."] and r.date_fields_missing, r.problems)
r = upd({"start_date": "2026-11-26"})
check("apply: 'kal se pehle' (ISO yesterday) -> refused", r.problems == ["Yeh tareekh beet chuki hai, aage ki tareekh boliye."])
r = upd({"start_date": "2026-11-28", "end_date": "2026-11-30"})
check("apply: a future ISO date still works (relative dates)", r.draft.start_date == "2026-11-28" and not r.problems)
r = upd({"start_day": "pachchis"})
check("apply: a day that isn't a number -> not a day field, nothing set", r.draft.start_date is None)
dr = D.TripDraftState(start_date="2026-12-25", end_date="2026-12-27")
r = upd({"end_day": 29}, draft=dr)
check("apply: only the end said later ('29 tak') -> 29 Dec after the saved start", r.draft.end_date == "2026-12-29", r.draft.end_date)

# ---------------------------------------------------------------- through the voice agent (the reported sentence)
USER = f"usr_dates_{uuid.uuid4().hex[:6]}"
CONVS = []
GOA = [{"id": "ChIJgoa", "place_id": "ChIJgoa", "name": "Goa", "latitude": 15.29, "longitude": 74.12, "city": "Goa, India"}]


class FakeTools:
    queue, calls = [], 0

    def __call__(self, messages, tools, **kw):
        FakeTools.calls += 1
        args = FakeTools.queue.pop(0)
        return {"content": None, "tool_calls": [{"name": "update_trip_draft", "arguments": args}]}


def ra(text, args=None, today=N27, conv=None):
    conv = conv or f"conv_dates_{uuid.uuid4().hex[:6]}"
    CONVS.append(conv)
    FakeTools.queue = [args] if args is not None else []
    with mock.patch.object(agent, "_draft_today", lambda: today):
        return agent.run_agent(text, "hi", user_id=USER, conversation_id=conv, screen="/home", trip=None, redis_conn=redis_conn), conv


with mock.patch.object(openai_client, "chat_tools", FakeTools()), \
        mock.patch.object(places, "search_places", lambda q: GOA if q.strip().lower() in ("goa", "गोवा") else []):
    EVIDENCE = "मुझे गोवा जाना है तीन दिन के लिए पच्चीस तारीख से दो बड़े लोग, एक छोटा बच्चा, बजट सत्तर हजार है।"
    FIELDS = {"destination": "गोवा", "days": 3, "start_day": 25, "adults": 2, "children": 1, "budget_inr": 70000}
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        r, c = ra(EVIDENCE, FIELDS, today=date(2026, 11, 26))
    check("evidence sentence (today 26 Nov) -> not refused; 25-27 December", r.error_code is None
          and D.load(redis_conn, USER, c).start_date == "2026-12-25" and D.load(redis_conn, USER, c).end_date == "2026-12-27", r.reply_text)
    check("evidence: log date_rolled_forward=true, no words or dates", "date_rolled_forward=true" in log.getvalue()
          and "पच्चीस" not in log.getvalue() and "2026-12-25" not in log.getvalue(), log.getvalue())
    r, c = ra("pata nahi", conv=c, today=date(2026, 11, 26))   # "Kahan se jaana hai?" -> skipped
    check("evidence: read-back says the rolled month", r.reply_text.endswith("25 December se 27 December, do raat. Sahi hai?"), r.reply_text)
    r, c = ra("nahi", conv=c, today=date(2026, 11, 26))
    check("evidence: 'nahi' at the read-back -> dates cleared, asked again (unchanged)", r.reply_text == agent.DATE_AGAIN["hi"]
          and D.load(redis_conn, USER, c).start_date is None, r.reply_text)

    for text, args, want in [
        ("Goa, 25 tarikh se 3 din", {"destination": "Goa", "start_day": 25, "days": 3}, ("2026-12-25", "2026-12-27")),
        ("Goa, पच्चीस तारीख से तीन दिन", {"destination": "Goa", "start_day": 25, "days": 3}, ("2026-12-25", "2026-12-27")),
        ("Goa from the 25th for 3 days", {"destination": "Goa", "start_day": 25, "days": 3}, ("2026-12-25", "2026-12-27")),
        ("Goa, 25 se 27", {"destination": "Goa", "start_day": 25, "end_day": 27}, ("2026-12-25", "2026-12-27")),
        ("Goa, 25 से 27 तक", {"destination": "Goa", "start_day": 25, "end_day": 27}, ("2026-12-25", "2026-12-27")),
        ("Goa, from the 25th to the 27th", {"destination": "Goa", "start_day": 25, "end_day": 27}, ("2026-12-25", "2026-12-27")),
        ("Goa, 27 tarikh se 2 din", {"destination": "Goa", "start_day": 27, "days": 2}, ("2026-11-27", "2026-11-28")),
        ("Goa, 5 November se 2 din", {"destination": "Goa", "start_day": 5, "start_month": 11, "days": 2}, ("2027-11-05", "2027-11-06")),
        ("Goa, पांच नवंबर से 2 दिन", {"destination": "Goa", "start_day": 5, "start_month": 11, "days": 2}, ("2027-11-05", "2027-11-06")),
    ]:
        r, c = ra(text, args)
        d = D.load(redis_conn, USER, c)
        check(f"{text!r} (today 27 Nov) -> {want[0]}..{want[1]}", r.error_code is None and (d.start_date, d.end_date) == want,
              (r.reply_text, d.start_date, d.end_date))
    for text, args, today, want in [
        ("Goa, 25 tarikh se 2 din", {"destination": "Goa", "start_day": 25, "days": 2}, N10, "2026-11-25"),
        ("Goa, 5 tarikh se 2 din", {"destination": "Goa", "start_day": 5, "days": 2}, D27, "2027-01-05"),
        ("Goa, तीस तारीख से 2 दिन", {"destination": "Goa", "start_day": 30, "days": 2}, date(2026, 1, 31), "2026-03-30"),
    ]:
        r, c = ra(text, args, today=today)
        check(f"{text!r} (today {today}) -> {want}", D.load(redis_conn, USER, c).start_date == want, r.reply_text)
    for text, args in [("Goa, 25 November 2025 se", {"destination": "Goa", "start_day": 25, "start_month": 11, "start_year": 2025}),
                       ("Goa, kal se pehle se", {"destination": "Goa", "start_date": "2026-11-26"})]:
        r, c = ra(text, args)
        check(f"{text!r} -> still refused", r.error_code == "refused_value" and r.reply_text == "Yeh tareekh beet chuki hai, aage ki tareekh boliye.",
              r.reply_text)
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        r, c = ra("Goa, 25 tarikh se", {"destination": "Goa", "start_date": "2026-11-25"})
    check("model skipped the new fields -> old behaviour (refused), log date_fields_missing=true",
          r.error_code == "refused_value" and "date_fields_missing=true" in log.getvalue(), log.getvalue())
    check("the prompt says: only the parts SPOKEN, never an assumed month or year",
          "ONLY the parts the user actually SPOKE" in agent.SYSTEM_PROMPT and "Never fill in a month or year you" in agent.SYSTEM_PROMPT)

for c in CONVS:
    D.delete(redis_conn, USER, c)
    P.clear(redis_conn, USER, c)
    agent.clear_memory(redis_conn, USER, c)
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
