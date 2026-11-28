"""
Bengali (bn, beta) as a voice language (feat/bengali). App DB = SQLite, Redis = local, the model / STT / TTS / place
search simulated. No real AI, STT, TTS or Google call.
Checks:
  1. every spoken {"hi", "en"} template in the voice files has a "bn" one with exactly the English placeholders
     (str.format fields / f-string expressions); the on-screen tables have none (they stay English for Bengali).
  2. the table row: bn selectable, STT "bn", TTS "bn-IN", the model line; the Bengali STT hint; TTS bn-IN.
  3. Bengali chosen: Bengali replies for a Hindi, an English and a Bengali utterance (ack, refusal, unclear, model
     down, crash, nothing heard), and the model is told to reply in Bengali.
  4. Bengali yes / no / cancel / thanks words are recognised; the Hindi and English words still give the same answers.
  5. Bengali numbers, months, budgets and purpose words; the read-back in Bengali.
  6. a full hotel booking said in Bengali (fake model never called): questions in Bengali, Bengali-script names kept,
     the screen's buttons and card in English, saved.
  7. a trip draft in Bengali with fake model outputs: questions, the read-back, the review in Bengali.
Run from backend/: python -m tests.test_voice_bengali
"""
import ast
import io
import json
import os
import re
import string
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
os.environ.pop("VOICE_STT_PROMPT", None)

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_test_")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'bn.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import main  # noqa: E402
import openai_client  # noqa: E402
import places  # noqa: E402
import booking_flow as BF  # noqa: E402
from models_trip import TripModel  # noqa: E402
from redis_client import redis_conn  # noqa: E402
from trip_lifecycle import today_ist  # noqa: E402
from trip_purpose import classify_purpose  # noqa: E402
from voice import agent, booking_voice as BV, draft as D, languages as L, pipeline, stt, tts  # noqa: E402
from voice.confirm_words import is_positive_confirmation  # noqa: E402

main.SessionLocal = database.SessionLocal
database.Base.metadata.create_all(bind=database.engine)

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if (detail != "" and not cond) else ""), flush=True)


# ---------------------------------------------------------------- 1. templates
FILES = ["voice/draft.py", "voice/agent.py", "voice/pipeline.py", "voice/booking_voice.py", "voice/pages.py",
         "voice/tools/actions.py", "voice/tools/lookups.py", "voice/tools/smart.py", "booking_flow.py",
         "tour_guide_service.py"]
# On screen (buttons, cards, status lines, consent, test note, map panel title, small note): English for Bengali.
SCREEN_ONLY = {"TEST_NOTE", "CONSENT", "OFFER", "LABELS", "CARD_LABELS", "NOW_LABELS", "STATUS_LABELS", "NOTIFY_LINES",
               "NEARBY_TITLE", "VOICE_NOTE"}


def owners(tree):
    own = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
            name = ast.unparse(n.targets[0] if isinstance(n, ast.Assign) else n.target)
            for sub in ast.walk(n.value):
                own.setdefault(sub, name)
    return own


def fields(node):
    """The placeholders of one template: str.format field names, or an f-string's expressions (with format spec)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return sorted(f for _, f, spec, _ in string.Formatter().parse(node.value) if f is not None)
    if isinstance(node, ast.JoinedStr):
        return sorted(ast.unparse(v) for v in node.values if isinstance(v, ast.FormattedValue))
    return None


templates, mismatched, missing, screen_with_bn = 0, [], [], []
for f in FILES:
    tree = ast.parse(open(f, encoding="utf-8").read())
    own = owners(tree)
    for n in ast.walk(tree):
        if not isinstance(n, ast.Dict):
            continue
        keys = [k.value if isinstance(k, ast.Constant) else None for k in n.keys]
        if "hi" not in keys or "en" not in keys:
            continue
        name = own.get(n, "<inline>")
        v = dict(zip(keys, n.values))
        if name in SCREEN_ONLY:
            if "bn" in v and name != "VOICE_NOTE":
                screen_with_bn.append(f"{f}:{name}")
            continue
        if "bn" not in v:
            missing.append(f"{f}:{n.lineno} {name}")
            continue
        pairs = (list(zip([ast.unparse(k) for k in v["en"].keys], v["en"].values, v["bn"].values))
                 if isinstance(v["en"], ast.Dict) else [(None, v["en"], v["bn"])])
        if isinstance(v["en"], ast.Dict) and [ast.unparse(k) for k in v["en"].keys] != [ast.unparse(k) for k in v["bn"].keys]:
            mismatched.append(f"{f}:{name} keys differ")
        for key, en, bn in pairs:
            templates += 1
            if fields(en) != fields(bn):
                mismatched.append(f"{f}:{name}[{key}] en={fields(en)} bn={fields(bn)}")
print("\n== 1. every spoken template has a Bengali one with the same placeholders")
check(f"no spoken template without bn ({templates} checked)", not missing and templates >= 260, missing[:10])
check("bn placeholders == en placeholders, nested keys the same", not mismatched, mismatched[:10])
check("on-screen tables have no bn (English for Bengali)", not screen_with_bn, screen_with_bn)
bn_texts = []
for f in FILES:
    tree = ast.parse(open(f, encoding="utf-8").read())
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict):
            keys = [k.value if isinstance(k, ast.Constant) else None for k in n.keys]
            if "bn" in keys and "hi" in keys:
                bn = dict(zip(keys, n.values))["bn"]
                for x in (bn.values if isinstance(bn, ast.Dict) else [bn]):
                    if isinstance(x, ast.Constant) and isinstance(x.value, str):
                        bn_texts.append(x.value)
BANGLA = re.compile(r"[ঀ-৿]")
TOKENS_OK = {"3AC", "2AC", "1AC", "3-star"}     # train classes / hotel stars are said as is in Bengali
latin_only = [t for t in bn_texts if t.strip() and not BANGLA.search(t) and t not in TOKENS_OK
              and re.sub(r"[{][^}]*[}]|[\s,.:;]", "", t)          # only placeholders left: fine
              and "Reply in" not in t and t != "Details may vary."]
check("Bengali templates are in Bangla script (except 3AC / 3-star style tokens)", not latin_only, latin_only[:5])

print("\n== 2. the table row, STT and TTS")
bn = L.LANGUAGES["bn"]
check("bn: selectable, templates, STT bn, TTS bn-IN, native name বাংলা, display 'Bengali (beta)'",
      bn.selectable and bn.has_templates and bn.stt_code == "bn" and bn.tts_code == "bn-IN" and bn.native_name == "বাংলা"
      and bn.name == "Bengali (beta)" and L.normalize_choice("bn") == "bn" and L.template_lang("bn") == "bn")
check("the model line", L.reply_rule("bn") == "- Always reply in Bengali, whatever language the user speaks; use Bangla script.")
check("tts: bn -> bn-IN (hi / en / ur unchanged)", tts.sarvam_language("bn") == "bn-IN" and tts.sarvam_language("hi") == "hi-IN"
      and tts.sarvam_language("en") == "en-IN" and tts.sarvam_language("ur") == "hi-IN")
check("screen_lang: bn -> en, hi / en as is", L.screen_lang("bn") == "en" and L.screen_lang("hi") == "hi" and L.screen_lang("en") == "en")
SENT = []


def fake_post(url, headers=None, files=None, data=None, timeout=None):
    SENT.append(data)
    return SimpleNamespace(status_code=200, json=lambda: {"text": "আমি দার্জিলিং যেতে চাই", "language": "bengali"})


PCM = b"\x00\x00" * 1600
with mock.patch.object(stt.requests, "post", fake_post):
    stt.OpenAITranscribeSTT().transcribe(PCM, languages=["bn"])
    stt.OpenAITranscribeSTT().transcribe(PCM)
check("STT pinned to bn sends languages[]=bn and the Bengali hint", ("languages[]", "bn") in SENT[0]
      and ("prompt", stt.LANGUAGE_PROMPTS["bn"]) in SENT[0], SENT[0])
check("auto: the Hinglish hint, no pin (as before)", ("prompt", stt.DEFAULT_HINGLISH_PROMPT) in SENT[1]
      and not any(k == "languages[]" for k, _ in SENT[1]), SENT[1])
check("the Bengali hint echoed back on a silent clip counts as nothing heard", stt.is_prompt_echo(stt.LANGUAGE_PROMPTS["bn"]))
FAKE = SimpleNamespace(provider="f", model="f", calls=[])


class FakeSTT:
    provider, model = "f", "f"

    def transcribe(self, pcm, **kw):
        FAKE.calls.append(kw)
        return stt.STTResult(text="hello", language="en", duration_ms=1, latency_ms=1, provider="f", model="f")


def ctx(language):
    return pipeline.TurnContext(turn_id="t", user_id="u", session_id="s", conversation_id=f"c{uuid.uuid4().hex[:6]}",
                                language=language)


with mock.patch.object(pipeline, "get_stt", lambda: FakeSTT()):
    pipeline.run_turn(PCM, ctx("bn"))
check("pipeline: STT pinned ['bn']", FAKE.calls == [{"languages": ["bn"]}], FAKE.calls)
TTS = []
res = pipeline.TurnResult(turn_id="t", ok=True, text="Goa mein kya dekhein?", language="hi")
with mock.patch.object(pipeline, "run_agent", lambda *a, **k: SimpleNamespace(
        reply_text="Calangute Beach dekhiye.", ui_actions=[], action="reply", llm_ms=0, tool_ms=0, note=None,
        note_attribution=None, pending_confirmation=None, error_code=None, error_detail=None, error_info={})), \
        mock.patch.object(pipeline, "synthesize_reply", lambda text, code: (TTS.append(tts.sarvam_language(code)), (None, "", 0, None))[1]):
    pipeline.make_reply(ctx("bn"), res)
check("pipeline: the reply is spoken with bn-IN", TTS == ["bn-IN"], TTS)
for choice, want in (("bn", pipeline.EMPTY_TRANSCRIPT_REPLY_BN), ("auto", pipeline.EMPTY_TRANSCRIPT_REPLY)):
    r = pipeline.TurnResult(turn_id="t", ok=True, text="", language="en")
    pipeline.decide_reply(ctx(choice), r)
    check(f"{choice}: nothing heard -> {want!r}", r.reply_text == want)

# ---------------------------------------------------------------- 3. Bengali chosen: Bengali replies
USER = f"usr_bn_{uuid.uuid4().hex[:6]}"
TODAY = today_ist()
d = lambda n: (TODAY + timedelta(days=n)).isoformat()  # noqa: E731


class FakeLLM:
    queue, calls = [], []

    def __call__(self, messages, tools, **kw):
        FakeLLM.calls.append(messages)
        if FakeLLM.queue:
            kind, payload = FakeLLM.queue.pop(0)
            if kind == "text":
                return {"content": payload, "tool_calls": []}
            return {"content": None, "tool_calls": [{"name": payload[0], "arguments": payload[1]}]}
        return {"content": "ঠিক আছে।", "tool_calls": []}


fake = FakeLLM()


def ra(text, conv, language="bn", stt_tag="bn", trip=None, queue=None):
    if queue is not None:
        FakeLLM.queue = list(queue)
    return agent.run_agent(text, stt_tag, user_id=USER, conversation_id=conv, screen="/home", trip=trip,
                           redis_conn=redis_conn, language=language)


def conv():
    return f"conv_bn_{uuid.uuid4().hex[:8]}"


print("\n== 3. Bengali chosen: Bengali replies whatever the user speaks")
with mock.patch.object(openai_client, "chat_tools", fake):
    for said, tag in (("thank you", "en"), ("धन्यवाद", "hi"), ("ধন্যবাদ", "bn")):
        check(f"ack for {said!r} -> Bengali", ra(said, conv(), stt_tag=tag).reply_text == agent.ACK_REPLY["bn"])
    for said in ("delete my trip", "meri trip delete karo", "আমার ট্রিপ মুছে দিন"):
        r = ra(said, conv())
        check(f"delete refused in Bengali for {said!r}", r.reply_text == agent.DELETE_REPLY["bn"], r.reply_text)
    check("garbled -> the Bengali unclear line", ra("?? !!", conv()).reply_text == agent.UNCLEAR_REPLY["bn"])
    FakeLLM.calls.clear()
    ra("what should I see in Goa?", conv(), stt_tag="en", queue=[("text", "ক্যালাঙ্গুট বিচ দেখুন।")])
    p = FakeLLM.calls[-1][0]["content"]
    check("the model is told: Always reply in Bengali ...; use Bangla script",
          L.reply_rule("bn") in p and agent.REPLY_LANGUAGE_LINE not in p)
    for said, tag in (("Goa mein kya dekhein?", "hi"), ("what should I see in Goa?", "en"), ("গোয়ায় কী দেখব?", "bn")):
        with mock.patch.object(openai_client, "chat_tools", side_effect=openai_client.LLMError("x")):
            r1 = ra(said, conv(), stt_tag=tag)
        with mock.patch.object(openai_client, "chat_tools", side_effect=RuntimeError("bug")), \
                redirect_stdout(io.StringIO()):
            r2 = ra(said, conv(), stt_tag=tag)
        check(f"model down / crash -> Bengali for {said!r}", r1.reply_text == agent.TRY_LATER_REPLY["bn"]
              and r2.reply_text == agent.FALLBACK_REPLY_BN, (r1.reply_text, r2.reply_text))
    r = ra("map kholo", conv(), queue=[("tool", ("navigate", {"page": "map"}))])
    check("a page confirmation in Bengali", r.reply_text == "ম্যাপ খুলে দিলাম।", r.reply_text)

print("\n== 4. Bengali yes / no / cancel words; Hindi and English unchanged")
for said, want in (("হ্যাঁ", "yes"), ("হ্যাঁ, ঠিক আছে", "yes"), ("ঠিক আছে", "yes"), ("অবশ্যই", "yes"), ("না", "no"),
                   ("না, দরকার নেই", "no"), ("বাতিল", "no"), ("থাক", "no"),
                   ("haan", "yes"), ("nahi", "no"), ("हाँ", "yes"), ("नहीं", "no"), ("yes", "yes"), ("no", "no"),
                   ("ok", "yes"), ("cancel", "no"), ("haan ji", "yes"), ("mat karo", "no")):
    check(f"yes_or_no({said!r}) -> {want}", agent.yes_or_no(said) == want, agent.yes_or_no(said))
for said, want in (("হ্যাঁ, বানিয়ে দিন", True), ("ঠিক আছে, করে দিন", True), ("না, বদলান", False),
                   ("হ্যাঁ, কিন্তু চার দিনের জন্য", False), ("haan bana do", True), ("बना दो", True), ("nahi ruko", False)):
    check(f"positive confirmation {said!r} -> {want}", is_positive_confirmation(said) == want)
check("cancel first word: বাতিল / ক্যানসেল (and कैंसल, cancel)", agent._starts_cancel("বাতিল করুন")
      and agent._starts_cancel("ক্যানসেল") and agent._starts_cancel("कैंसल करो") and agent._starts_cancel("cancel karo"))
check("booking: যেকোনো / আপনিই ঠিক করুন = 'you decide'", BV.is_decide(BV.tokens("যেকোনো"))
      and BV.is_decide(BV.tokens("আপনিই ঠিক করুন")) and BV.is_decide(BV.tokens("aap decide karo")))
check("booking cancel: বুকিং বাতিল / এখন না (and abhi nahi)", BV.is_cancel("বুকিং বাতিল") and BV.is_cancel("এখন না")
      and BV.is_cancel("abhi nahi"))
check("acknowledgement: ধন্যবাদ / খুব ভালো, ঠিক আছে (and dhanyavaad)", agent.is_acknowledgement("ধন্যবাদ")
      and agent.is_acknowledgement("খুব ভালো, ঠিক আছে") and agent.is_acknowledgement("dhanyavaad"))
check("origin skip: জানি না (and pata nahi)", agent.origin_skip_kind("জানি না", True) == "short"
      and agent.origin_skip_kind("pata nahi", True) == "short")

print("\n== 5. numbers, months, budget, purpose")
for raw, want in (("পঁচিশ", 25), ("একশো", 100), ("দুটো", 2), ("কেউ নেই", 0), ("১২", 12), ("do", 2), ("teen", 3), ("5", 5)):
    check(f"parse_int({raw!r}) -> {want}", D.parse_int(raw) == want, D.parse_int(raw))
for raw, want in (("পঞ্চাশ হাজার", 50000), ("৫০ হাজার", 50000), ("1.5 লাখ", 150000), ("50 hazaar", 50000)):
    check(f"parse_budget({raw!r}) -> {want}", D.parse_budget(raw) == want, D.parse_budget(raw))
check("all 101 Bengali numbers 0..100 read back", all(D.parse_int(w) == i for i, w in enumerate(D.BN.BN_NUMBERS)))
check("Bengali month names -> 1..12", [D.BN.month(m) for m in D.BN_MONTHS] == list(range(1, 13)))
check("start_day পঁচিশ + start_month ডিসেম্বর -> (25, 12)", D._said_parts({"start_day": "পঁচিশ", "start_month": "ডিসেম্বর"}, "start")[:2] == (25, 12))
for said, want in (("হ্যাকাথনের জন্য", ("event", "hackathon")), ("অফিসের মিটিং", ("business", "office")),
                   ("বেড়াতে যাচ্ছি", ("leisure", None)), ("তীর্থে যাব", ("pilgrimage", None)),
                   ("hackathon ke liye", ("event", "hackathon")), ("kaam se", ("business", "kaam"))):
    check(f"purpose {said!r} -> {want}", classify_purpose(said)[:2] == want, classify_purpose(said))
check("purpose: জানি না = skipped", classify_purpose("জানি না") == (None, None, True))
dd = D.TripDraftState(destination={"name": "Darjeeling"}, origin_city={"name": "Kolkata"}, start_date=d(30), end_date=d(32),
                      adults=2, children=1, budget_inr=40000, purpose_type="event", purpose_text="hackathon",
                      base_area={"name": "Mall Road"})
rb = D.readback(dd, "bn")
check("read-back in Bengali", rb.startswith("Kolkata থেকে Darjeeling, ") and "2 রাত" in rb and "2 জন প্রাপ্তবয়স্ক, 1 জন বাচ্চা" in rb
      and "আপনার hackathon-এর জন্য, Mall Road-এর কাছে" in rb and rb.endswith("। ঠিক আছে?"), rb)
check("read-back hi / en unchanged", D.readback(dd, "hi").endswith("Sahi hai?") and "do bade log, ek bachcha" in D.readback(dd, "hi")
      and D.readback(dd, "en").startswith("Kolkata to Darjeeling") and D.readback(dd, "en").endswith("Is that right?"))

# ---------------------------------------------------------------- 6. booking in Bengali
NOW = datetime.now(timezone.utc)


def make_trip():
    tid = f"trip_bn_{uuid.uuid4().hex[:8]}"
    with database.SessionLocal() as db:
        db.add(TripModel(id=tid, user_id=USER, title="Darjeeling", status="PLANNING", start_date=d(20), end_date=d(22),
                         total_days=3, destination={"name": "Darjeeling"},
                         travelers=[{"id": f"tr_{i}", "type": "ADULT"} for i in range(2)], budget={"targetAmount": 40000},
                         created_at=NOW, updated_at=NOW, itinerary_status="READY"))
        db.commit()
    return tid


print("\n== 6. a hotel booking said in Bengali")
with mock.patch.object(openai_client, "chat_tools", fake):
    T = make_trip()
    TRIP = agent.TripInfo(title="Darjeeling", start_date=d(20), end_date=d(22), id=T)
    C = conv()
    n = len(FakeLLM.calls)
    said = ["আমি হোটেল বুক করতে চাই", "বাজেট", "দুটো রুম", "রোশন, ত্রিশ বছর", "মোহন, চল্লিশ বছর", "৯৮৭৬৫৪৩২১০", "হ্যাঁ"]
    replies = [ra(w, C, trip=TRIP) for w in said]
    check("started: the hotel question in Bengali", replies[0].action == "booking"
          and replies[0].reply_text.startswith(BF.PROMPTS["bn"]["hotel_type"]), replies[0].reply_text)
    check("every booking reply is in Bangla script", all(BANGLA.search(r.reply_text) for r in replies),
          [r.reply_text for r in replies])
    st = BF.load(redis_conn, USER, T)
    check("Bengali-script names kept (রোশন, মোহন), ages 30 and 40, 2 rooms, phone read from Bengali digits",
          [t["name"] for t in st.travellers] == ["রোশন", "মোহন"] and [t["age"] for t in st.travellers] == [30, 40]
          and st.answers.get("hotel_rooms") == 2 and st.phone == "9876543210", (st.travellers, st.answers, st.phone))
    check("the review question in Bengali", replies[-1].reply_text.endswith(BF.PROMPTS["bn"]["review"])
          and BF.current_question(st) == "review", replies[-1].reply_text)
    view = BF.view(st, "bn")
    check("the screen: buttons, card labels and consent in English; the question in Bengali",
          view["card"]["rows"][0]["label"] == BF.CARD_LABELS["en"].get(view["card"]["rows"][0]["key"], view["card"]["rows"][0]["label"])
          and view.get("consent") == BF.CONSENT["en"] and BANGLA.search(view["prompt"] or "") is not None, view)
    r = ra("হ্যাঁ", C, trip=TRIP)
    check("হ্যাঁ at the review saves the booking (Bengali reply)", r.action == "booking" and r.step == "done"
          and "BR-" in r.reply_text and BANGLA.search(r.reply_text), r.reply_text)
    check("no model call in the booking", len(FakeLLM.calls) == n)
    check("a Hindi booking still refuses Bengali-script names", BF.name_problem("রোশন") == "script"
          and BF.name_problem("রোশন", lang="bn") is None and BF.name_problem("रोशन") is None)

# ---------------------------------------------------------------- 7. trip draft in Bengali
print("\n== 7. a trip draft in Bengali (fake model outputs)")
PLACES = {"darjeeling": [{"id": "ChIJdj", "place_id": "ChIJdj", "name": "Darjeeling", "latitude": 27.04, "longitude": 88.26,
                          "city": "Darjeeling, West Bengal, India"}],
          "kolkata": [{"id": "ChIJkol", "place_id": "ChIJkol", "name": "Kolkata", "latitude": 22.57, "longitude": 88.36,
                       "city": "Kolkata, West Bengal, India"}]}
start = TODAY + timedelta(days=40)
with mock.patch.object(openai_client, "chat_tools", fake), \
        mock.patch.object(places, "search_places", lambda q: PLACES.get(q.strip().lower(), [])):
    C = conv()
    r1 = ra("আমি দার্জিলিং যেতে চাই", C, queue=[("tool", ("update_trip_draft", {"destination": "Darjeeling"}))])
    check("destination set; the next question in Bengali", r1.action == "trip_draft" and "Darjeeling" in r1.reply_text
          and D.QUESTIONS["start_date"]["bn"] in r1.reply_text, r1.reply_text)
    r2 = ra(f"{start.day} {D.BN_MONTHS[start.month - 1]} থেকে তিন দিন, দুজন, কোনো বাচ্চা নেই, বাজেট পঞ্চাশ হাজার", C,
            queue=[("tool", ("update_trip_draft", {"start_day": str(start.day), "start_month": D.BN_MONTHS[start.month - 1],
                                                    "days": "তিন", "adults": "দুই", "children": "কেউ নেই",
                                                    "budget_inr": "পঞ্চাশ হাজার"}))])
    dr = D.load(redis_conn, USER, C)
    check("Bengali words stored as values: start, 3 days, 2 adults, 0 children, ₹50,000",
          dr.start_date == start.isoformat() and dr.end_date == (start + timedelta(days=2)).isoformat()
          and dr.adults == 2 and dr.children == 0 and dr.budget_inr == 50000, (dr.start_date, dr.end_date, dr.adults,
                                                                              dr.children, dr.budget_inr))
    check("then the starting city question in Bengali", D.QUESTIONS["origin_city"]["bn"] in r2.reply_text, r2.reply_text)
    r3 = ra("কলকাতা থেকে", C, queue=[("tool", ("update_trip_draft", {"origin_city": "Kolkata"}))])
    check("then the purpose question in Bengali", D.QUESTIONS["purpose"]["bn"] in r3.reply_text, r3.reply_text)
    r4 = ra("বেড়াতে যাচ্ছি", C, queue=[("tool", ("update_trip_draft", {"purpose": "বেড়াতে যাচ্ছি"}))])
    check("purpose classified by code from the Bengali words (leisure), then the read-back in Bengali", r4.step == "confirm_date"
          and r4.reply_text.endswith("ঠিক আছে?") and "Kolkata থেকে Darjeeling" in r4.reply_text
          and "বেড়ানোর জন্য" in r4.reply_text, r4.reply_text)
    r5 = ra("হ্যাঁ", C)
    check("হ্যাঁ -> the review page, told in Bengali", r5.reply_text.endswith(agent.READY_REPLY["bn"])
          and any(a.get("type") == "open_review" for a in r5.ui_actions), (r5.reply_text, r5.ui_actions))

for k in redis_conn.scan_iter(f"*{USER}*"):
    redis_conn.delete(k)
with database.SessionLocal() as db:
    db.query(TripModel).filter(TripModel.user_id == USER).delete()
    db.commit()

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
