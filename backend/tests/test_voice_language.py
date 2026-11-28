"""
The voice language the user chooses (feat/language): voice/languages.py, the pipeline, the agent, TTS.
App DB = SQLite, Redis = local, the model / STT / TTS / place search simulated. No real AI, STT, TTS or Google call.
Checks:
  1. the language table: every entry complete; unknown / empty / wrong type -> "auto".
  2. a language without templates -> English templates, "[LANG] templates=fallback_en lang=<code>" once per conversation.
  3. "auto" = as before: the same replies and the same model prompt with no language, "auto" or an unknown value.
  4. "hi": Hindi templates even for an English utterance, the model told "Always reply in Hindi ...".
  5. "en": English templates even for a Hindi utterance (also the lines that were Hinglish-only), "Always reply in
     English ...".
  6. the pipeline: STT pinned to the chosen code (auto: transcribe(pcm) exactly as before), the TTS code follows the
     choice (auto: the reply's own words), an empty transcript and a crash reply in the chosen language.
  7. booking by voice with "en" (Hindi words said) and with "hi" (English words said): questions in the chosen language,
     yes / no understood either way, the booking saved.
Run from backend/: python -m tests.test_voice_language
"""
import io
import os
import sys
import tempfile
import uuid
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
os.environ["AI_PROVIDER"] = "mock"
os.environ["OPENAI_API_KEY"] = "test-key-not-real"
os.environ["VOICE_TTS_ENABLED"] = "false"
os.environ.pop("VOICE_DEBUG_STORE", None)
os.environ.pop("BOOKING_NOTIFY_ENABLED", None)
os.environ.pop("VOICE_STT_LANGUAGES", None)

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'lang.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
import openai_client  # noqa: E402
import booking_flow as BF  # noqa: E402
from models_trip import TripModel  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from trip_lifecycle import today_ist  # noqa: E402
from voice import agent, languages as L, pipeline, tts  # noqa: E402
from voice.stt import STTResult  # noqa: E402

main.SessionLocal = database.SessionLocal
database.Base.metadata.create_all(bind=database.engine)

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if (detail != "" and not cond) else ""), flush=True)


USER = f"usr_lang_{uuid.uuid4().hex[:6]}"
TODAY = today_ist()
d = lambda n: (TODAY + timedelta(days=n)).isoformat()  # noqa: E731


class FakeLLM:
    """Records the prompts; answers with a queued tool call / text, else plain text."""
    queue, calls = [], []

    def __call__(self, messages, tools, **kw):
        FakeLLM.calls.append(messages)
        if FakeLLM.queue:
            kind, payload = FakeLLM.queue.pop(0)
            if kind == "text":
                return {"content": payload, "tool_calls": []}
            return {"content": None, "tool_calls": [{"name": payload[0], "arguments": payload[1]}]}
        return {"content": "Theek hai.", "tool_calls": []}


fake = FakeLLM()


def ra(text, conv, language=..., stt="hi", trip=None, queue=None):
    """One agent turn; language=... means the argument is not passed at all (the call as before this change)."""
    if queue is not None:
        FakeLLM.queue = list(queue)
    kw = {} if language is ... else {"language": language}
    return agent.run_agent(text, stt, user_id=USER, conversation_id=conv, screen="/home", trip=trip,
                           redis_conn=redis_conn, **kw)


def conv():
    return f"conv_lang_{uuid.uuid4().hex[:8]}"


def system_prompt():
    return FakeLLM.calls[-1][0]["content"]


print("\n== 1. the language table")
for code, lang in L.LANGUAGES.items():
    check(f"{code}: complete entry", lang.code == code and lang.name and lang.native_name and lang.stt_code
          and lang.tts_code.endswith("-IN") and lang.prompt_name and isinstance(lang.has_templates, bool))
check("hi and en only, both with templates", sorted(L.LANGUAGES) == ["en", "hi"]
      and all(x.has_templates and x.selectable for x in L.LANGUAGES.values()))
for raw, want in (("hi", "hi"), ("en", "en"), (" EN ", "en"), ("auto", "auto"), ("", "auto"), (None, "auto"),
                  ("fr", "auto"), ("bn", "auto"), (5, "auto"), (["hi"], "auto"), ("hindi", "auto"), ("h" * 500, "auto")):
    check(f"normalize_choice({raw!r:.20}) -> {want}", L.normalize_choice(raw) == want, L.normalize_choice(raw))
check("auto: no template language, no STT pin, no TTS code, no prompt rule",
      L.template_lang("auto") is None and L.stt_languages("auto") is None and L.tts_code("xx") is None
      and L.reply_rule(None) is None)
check("hi: STT ['hi'], TTS hi-IN, template hi", L.stt_languages("hi") == ["hi"] and L.tts_code("hi") == "hi-IN"
      and L.template_lang("hi") == "hi")
check("en: STT ['en'], TTS en-IN, template en", L.stt_languages("en") == ["en"] and L.tts_code("en") == "en-IN"
      and L.template_lang("en") == "en")
check("tts.sarvam_language unchanged for hi / ur / en / unknown", tts.sarvam_language("hi") == "hi-IN"
      and tts.sarvam_language("ur") == "hi-IN" and tts.sarvam_language("en") == "en-IN"
      and tts.sarvam_language(None) == "hi-IN" and tts.sarvam_language("zz") == "hi-IN")

print("\n== 2. a language without templates: English templates, logged once per conversation")
BN = L.Language("bn", "Bengali", "বাংলা", stt_code="bn", tts_code="bn-IN", prompt_name="Bengali", has_templates=False)
with mock.patch.dict(L.LANGUAGES, {"bn": BN}):
    buf = io.StringIO()
    with redirect_stdout(buf):
        a1, a2, a3 = L.template_lang("bn", "c1"), L.template_lang("bn", "c1"), L.template_lang("bn", "c2")
    lines = [x for x in buf.getvalue().splitlines() if x.startswith("[LANG]")]
    check("bn -> English templates", (a1, a2, a3) == ("en", "en", "en"), (a1, a2, a3))
    check("'[LANG] templates=fallback_en lang=bn' once per conversation (c1 once, c2 once)",
          lines == ["[LANG] templates=fallback_en lang=bn"] * 2, lines)
    check("bn: its own STT, TTS and prompt line", L.stt_languages("bn") == ["bn"] and tts.sarvam_language("bn") == "bn-IN"
          and L.reply_rule("bn") == "- Always reply in Bengali, whatever language the user speaks.")
    FakeLLM.calls.clear()
    with mock.patch.object(openai_client, "chat_tools", fake), redirect_stdout(io.StringIO()):
        r = ra("thank you", conv(), language="bn")
    check("bn turn: English ack template", r.reply_text == agent.ACK_REPLY["en"], r.reply_text)

with mock.patch.object(openai_client, "chat_tools", fake):
    print("\n== 3. auto = as before")
    # recorded turns: (said, STT tag, queued model answer or None)
    TURNS = [("Itinerary kholo", "hi", [("tool", ("navigate", {"page": "itinerary"}))]),
             ("open my itinerary", "en", [("tool", ("navigate", {"page": "itinerary"}))]),
             ("Goa mein kya dekhein?", "hi", [("text", "Calangute Beach dekhiye.")]),
             ("what should I see in Goa?", "en", [("text", "Visit Calangute Beach.")]),
             ("thank you", "en", None), ("धन्यवाद", "hi", None), ("?? !!", "en", None),
             ("meri trip delete karo", "hi", None), ("delete my trip", "en", None)]
    for said, tag, q in TURNS:
        outs, prompts = [], []
        for language in (..., None, "auto", "xx", 7):
            FakeLLM.calls.clear()
            r = ra(said, conv(), language=language, stt=tag, queue=list(q) if q else [])
            outs.append((r.reply_text, r.action, r.ui_actions))
            prompts.append(system_prompt().split("Current screen")[0] if FakeLLM.calls else None)
        check(f"auto '{said}': same reply with no / None / auto / unknown language", len(set(map(repr, outs))) == 1, outs)
        if prompts[0]:
            check(f"auto '{said}': same model prompt, with the old reply-language line",
                  len(set(prompts)) == 1 and agent.REPLY_LANGUAGE_LINE in prompts[0] and "Always reply in" not in prompts[0])
    check("auto: English 'thank you' -> English ack, Hindi 'धन्यवाद' -> Hinglish ack (detected, as before)",
          ra("thank you", conv(), stt="en").reply_text == agent.ACK_REPLY["en"]
          and ra("धन्यवाद", conv()).reply_text == agent.ACK_REPLY["hi"])
    check("auto: garbled words -> the Hinglish unclear line (as before)",
          ra("?? !!", conv(), stt="en").reply_text == agent.UNCLEAR_REPLY["en"] == "Samajh nahi aaya, phir se boliye.")

    print("\n== 4. hi: Hindi replies even for English words")
    FakeLLM.calls.clear()
    r = ra("what should I see in Goa?", conv(), language="hi", stt="en", queue=[("text", "Calangute Beach dekhiye.")])
    p = system_prompt()
    check("the model is told: Always reply in Hindi, whatever language the user speaks",
          "- Always reply in Hindi (Hinglish in Roman script is fine), whatever language the user speaks." in p
          and agent.REPLY_LANGUAGE_LINE not in p, p[:400])
    check("English 'thank you' -> the Hinglish ack", ra("thank you", conv(), language="hi", stt="en").reply_text
          == agent.ACK_REPLY["hi"])
    check("English 'delete my trip' -> the Hinglish refusal", ra("delete my trip", conv(), language="hi", stt="en").reply_text
          == agent.delete_refused("hi").reply_text)
    check("garbled words -> the Hinglish unclear line", ra("?? !!", conv(), language="hi", stt="en").reply_text
          == agent.UNCLEAR_REPLY["hi"])

    print("\n== 5. en: English replies even for Hindi words")
    FakeLLM.calls.clear()
    r = ra("Goa mein kya dekhein?", conv(), language="en", queue=[("text", "Visit Calangute Beach.")])
    p = system_prompt()
    check("the model is told: Always reply in English, whatever language the user speaks",
          "- Always reply in English, whatever language the user speaks." in p and agent.REPLY_LANGUAGE_LINE not in p)
    check("Hindi 'धन्यवाद' -> the English ack", ra("धन्यवाद", conv(), language="en").reply_text == agent.ACK_REPLY["en"])
    check("Hinglish 'meri trip delete karo' -> the English refusal",
          ra("meri trip delete karo", conv(), language="en").reply_text == agent.delete_refused("en").reply_text)
    check("garbled words -> English (the Hinglish-only unclear line has an English twin now)",
          ra("?? !!", conv(), language="en").reply_text == agent.UNCLEAR_REPLY_EN)
    FakeLLM.queue = []
    with mock.patch.object(openai_client, "chat_tools", side_effect=openai_client.LLMError("x")):
        r_en = ra("Goa mein kya dekhein?", conv(), language="en")
        r_auto = ra("Goa mein kya dekhein?", conv())
    check("model down: TRY_LATER in English for en, Hinglish for auto (Hindi words)",
          r_en.reply_text == agent.TRY_LATER_REPLY["en"] and r_auto.reply_text == agent.TRY_LATER_REPLY["hi"],
          (r_en.reply_text, r_auto.reply_text))
    with mock.patch.object(openai_client, "chat_tools", side_effect=RuntimeError("bug")):
        r_en = ra("Goa mein kya dekhein?", conv(), language="en")
        r_auto = ra("Goa mein kya dekhein?", conv())
    check("a crash: FALLBACK in English for en, the Hinglish line for auto",
          r_en.reply_text == agent.FALLBACK_REPLY_EN and r_auto.reply_text == agent.FALLBACK_REPLY,
          (r_en.reply_text, r_auto.reply_text))

print("\n== 6. the pipeline: STT pin, TTS code")


class FakeSTT:
    provider, model = "fake", "fake"
    calls = []

    def __init__(self, text="Goa mein kya dekhein?", language="hi"):
        self.text, self.language = text, language

    def transcribe(self, pcm, **kw):
        FakeSTT.calls.append(kw)
        return STTResult(text=self.text, language=self.language, duration_ms=100, latency_ms=5, provider="fake", model="fake")


class OldSTT:
    """A transcriber with the old signature: auto must call it exactly as before (no keyword)."""
    provider, model = "old", "old"

    def transcribe(self, pcm):
        return STTResult(text="hello", language="en", duration_ms=100, latency_ms=5, provider="old", model="old")


def ctx(language=L.AUTO):
    return pipeline.TurnContext(turn_id="t", user_id=USER, session_id="s", conversation_id=conv(),
                                language=language)


PCM = b"\x00\x00" * 1600
for choice, want in (("hi", {"languages": ["hi"]}), ("en", {"languages": ["en"]})):
    FakeSTT.calls.clear()
    with mock.patch.object(pipeline, "get_stt", lambda: FakeSTT()):
        pipeline.run_turn(PCM, ctx(choice))
    check(f"{choice}: STT pinned {want['languages']}", FakeSTT.calls == [want], FakeSTT.calls)
with mock.patch.object(pipeline, "get_stt", lambda: OldSTT()):
    res = pipeline.run_turn(PCM, ctx())
check("auto: transcribe(pcm) called exactly as before (an old-signature transcriber works)", res.ok and res.text == "hello")
check("TurnContext: the default language is auto", pipeline.TurnContext("t", "u", "s").language == "auto")

TTS_CALLS = []


def fake_tts(text, code):
    TTS_CALLS.append((text, code, tts.sarvam_language(code)))
    return None, tts.REPLY_MIME, 0, "tts_disabled"


AGENT_KW = []


def fake_agent(reply):
    def run(text, stt_language, **kw):
        AGENT_KW.append(kw)
        return SimpleNamespace(reply_text=reply, ui_actions=[], action="reply", llm_ms=0, tool_ms=0, note=None,
                               note_attribution=None, pending_confirmation=None, error_code=None, error_detail=None,
                               error_info={})
    return run


for choice, reply, want in (("auto", "Calangute Beach dekhiye, bahut accha hai.", "hi-IN"), ("auto", "Visit Calangute Beach.", "en-IN"),
                            ("en", "Calangute Beach dekhiye.", "en-IN"), ("hi", "Visit Calangute Beach.", "hi-IN")):
    TTS_CALLS.clear()
    AGENT_KW.clear()
    res = pipeline.TurnResult(turn_id="t", ok=True, text="Goa mein kya dekhein?", language="hi")
    with mock.patch.object(pipeline, "run_agent", fake_agent(reply)), mock.patch.object(pipeline, "synthesize_reply", fake_tts):
        pipeline.make_reply(ctx(choice), res)
    check(f"{choice}, reply {reply!r}: TTS {want}", TTS_CALLS and TTS_CALLS[0][2] == want, TTS_CALLS)
    check(f"{choice}: run_agent gets " + ("no language argument (as before)" if choice == "auto" else f"language={choice}"),
          AGENT_KW == [{**AGENT_KW[0], **({} if choice == "auto" else {"language": choice})}]
          and ("language" in AGENT_KW[0]) == (choice != "auto"), AGENT_KW)

for choice, want in (("auto", pipeline.EMPTY_TRANSCRIPT_REPLY), ("hi", pipeline.EMPTY_TRANSCRIPT_REPLY),
                     ("en", pipeline.EMPTY_TRANSCRIPT_REPLY_EN)):
    res = pipeline.TurnResult(turn_id="t", ok=True, text="", language="en")
    pipeline.decide_reply(ctx(choice), res)
    check(f"{choice}: nothing heard -> {want!r}", res.reply_text == want, res.reply_text)
for choice, want in (("auto", agent.FALLBACK_REPLY), ("en", agent.FALLBACK_REPLY_EN)):
    res = pipeline.TurnResult(turn_id="t", ok=True, text="hello there", language="en")
    with mock.patch.object(pipeline, "run_agent", side_effect=RuntimeError("boom")):
        pipeline.decide_reply(ctx(choice), res)
    check(f"{choice}: agent crash -> {want!r}", res.reply_text == want, res.reply_text)

print("\n== 7. booking by voice in the chosen language")
NOW = datetime.now(timezone.utc)


def make_trip():
    tid = f"trip_lang_{uuid.uuid4().hex[:8]}"
    with database.SessionLocal() as db:
        db.add(TripModel(id=tid, user_id=USER, title="Goa", status="PLANNING", start_date=d(20), end_date=d(22), total_days=3,
                         destination={"name": "Goa"}, travelers=[{"id": f"tr_{i}", "type": "ADULT"} for i in range(2)],
                         budget={"targetAmount": 40000}, created_at=NOW, updated_at=NOW, itinerary_status="READY"))
        db.commit()
    return tid


with mock.patch.object(openai_client, "chat_tools", fake):
    for choice, words, yes, first_q, review_q in (
            ("en", ("hotel book karwana hai", "budget", "do kamre", "Roshan, 30 saal", "Mohan, 40 saal", "9876543210", "haan"),
             "हाँ", BF.PROMPTS["en"]["hotel_type"], BF.PROMPTS["en"]["review"]),
            ("hi", ("I want to book a hotel", "budget", "2 rooms", "Roshan, 30", "Mohan, 40", "9876543210", "yes"),
             "yes", BF.PROMPTS["hi"]["hotel_type"], BF.PROMPTS["hi"]["review"])):
        T = make_trip()
        TRIP = agent.TripInfo(title="Goa", start_date=d(20), end_date=d(22), id=T)
        C = conv()
        n = len(FakeLLM.calls)
        replies = [ra(w, C, language=choice, stt="en" if choice == "hi" else "hi", trip=TRIP) for w in words]
        check(f"{choice}: booking started, first question in the chosen language", replies[0].action == "booking"
              and replies[0].reply_text.startswith(first_q), replies[0].reply_text)
        check(f"{choice}: the review question in the chosen language", replies[-1].reply_text.endswith(review_q)
              and BF.current_question(BF.load(redis_conn, USER, T)) == "review", [r.reply_text for r in replies])
        r = ra(yes, C, language=choice, trip=TRIP)
        check(f"{choice}: '{yes}' at the review saves the booking", r.action == "booking" and r.step == "done"
              and "BR-" in r.reply_text, r.reply_text)
        check(f"{choice}: no model call in the booking", len(FakeLLM.calls) == n)

for k in redis_conn.scan_iter(f"*{USER}*"):
    redis_conn.delete(k)
with database.SessionLocal() as db:
    db.query(TripModel).filter(TripModel.user_id == USER).delete()
    db.commit()

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
