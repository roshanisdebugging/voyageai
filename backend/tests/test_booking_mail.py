"""
Booking stage 4 checks: the partner email (booking_mail.py). SMTP is always simulated: nothing leaves this machine.
App DB = SQLite (throwaway file), Redis = local (one booking key, deleted). The real backend/.env is never read.
success -> sent; auth failure -> failed (request kept); timeout -> one retry then failed; timeout then OK -> sent;
never sent twice (also two threads at once); flag off -> nothing sent and the old wording; Hindi names in the body;
subject format; the STARTTLS / login / timeout calls; the send never blocks; logs without personal data.
Run from backend/: python -m tests.test_booking_mail
"""
import io
import logging
import os
import smtplib
import socket
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
for _k in ("BOOKING_NOTIFY_ENABLED", "SMTP_HOST", "SMTP_PORT", "BOOKING_REPLY_HOURS"):
    os.environ.pop(_k, None)
os.environ.update({"SMTP_USER": "sender@example.com", "SMTP_PASSWORD": "fake-smtp-pw", "PARTNER_EMAIL": "partner@example.com"})

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)
SCRATCH = tempfile.mkdtemp(prefix="voyageai_mail_")

from sqlalchemy import create_engine, text as sql  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database  # noqa: E402

database.engine = create_engine(f"sqlite:///{os.path.join(SCRATCH, 'mail.db')}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import models_db  # noqa: E402,F401
import models_trip  # noqa: E402,F401
import models_place  # noqa: E402
import booking_flow as BF  # noqa: E402
import booking_mail as M  # noqa: E402
from models_booking import BookingRequestModel as R  # noqa: E402
from redis_client import redis_conn  # noqa: E402

database.Base.metadata.create_all(bind=database.engine)

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


log_buf = io.StringIO()
_h = logging.StreamHandler(log_buf)
for _name in ("booking", "voice"):
    logging.getLogger(_name).addHandler(_h)
    logging.getLogger(_name).setLevel(logging.INFO)

NOW = datetime.now(timezone.utc).isoformat()
START = (datetime.now(timezone.utc) + timedelta(days=8)).date()
UID = f"usr_mail_{uuid.uuid4().hex[:6]}"
with database.SessionLocal() as db:
    db.add(models_place.CityModel(id="city_kol", lookup_key="kolkata|west bengal", name="Kolkata", region="West Bengal",
                                  country="India", latitude=22.57, longitude=88.36, created_at=datetime.now(timezone.utc)))
    db.commit()


def make_trip():
    tid = f"trip_mail_{uuid.uuid4().hex[:8]}"
    with database.SessionLocal() as db:
        db.add(models_trip.TripModel(id=tid, user_id=UID, title="Goa", status="PLANNING", start_date=START.isoformat(),
                                     end_date=(START + timedelta(days=3)).isoformat(), total_days=4,
                                     destination={"name": "Goa"}, travelers=[{"type": "ADULT"}, {"type": "ADULT"}],
                                     budget={}, created_at=NOW, updated_at=NOW, itinerary_status="READY",
                                     origin_city_id="city_kol"))
        db.commit()
    return tid


def make_request(enabled=True):
    tid = make_trip()
    s = BF.BookingState(trip_id=tid, adults=2, children=0, services=["flight", "hotel"],
                        answers={"flight_time": "morning", "flight_airline": "IndiGo", "hotel_type": "3star", "hotel_rooms": BF.ANY},
                        travellers=[{"name": "रोशन झा", "age": 25}, {"name": "Kamla Devi", "age": 68}], phone="9876543210")
    if enabled:
        os.environ["BOOKING_NOTIFY_ENABLED"] = "true"
    try:
        req, _ = BF.save_request(s, UID)
    finally:
        os.environ.pop("BOOKING_NOTIFY_ENABLED", None)
    return tid, req["requestNo"]


def row(no):
    with database.SessionLocal() as db:
        return db.query(R).filter(R.request_no == no).first()


class Sender:
    """Simulated SMTP: raises the queued errors in order, then succeeds."""

    def __init__(self, *errors):
        self.errors, self.sent = list(errors), []

    def __call__(self, msg, cfg):
        if self.errors:
            raise self.errors.pop(0)
        self.sent.append((msg, cfg))


naps = []
nap = naps.append

# ---------------- the message
tid, no = make_request()
check("flag on: a new request starts as notify pending", row(no).notify_status == "pending")
with database.SessionLocal() as db:
    r0 = db.query(R).filter(R.request_no == no).first()
    msg = M.build_message(M._row_dict(r0), M._trip_info(db, tid), "sender@example.com", "partner@example.com")
body = msg.get_content()
subject = msg["Subject"]
check("subject: '[Cruiser] Booking request BR-xxxx | Kolkata -> Goa | <start date>'",
      subject == f"[Cruiser] Booking request {no} | Kolkata -> Goa | {START.strftime('%d %b %Y')}", subject)
check("plain text, UTF-8, no HTML, no links", msg.get_content_type() == "text/plain" and msg.get_content_charset() == "utf-8"
      and "<" not in body and "http" not in body and not msg.is_multipart())
check("From = SMTP_USER, To = PARTNER_EMAIL", msg["From"] == "sender@example.com" and msg["To"] == "partner@example.com")
check("body: Hindi traveller name kept exactly", "1. रोशन झा, 25 years" in body and "2. Kamla Devi, 68 years" in body, body)
check("body: number, created time (IST), route and dates", f"Booking request: {no}" in body and " IST" in body
      and "Route: Kolkata -> Goa" in body and f"Dates: {START.strftime('%d %b %Y')} to " in body)
check("body: services with each answer", "Flight:" in body and "  - Flight time: Morning" in body and "  - Airline: IndiGo" in body
      and "Hotel:" in body and "  - Hotel type: 3-star" in body and "  - Rooms: Any (customer said: aap decide karo)" in body, body)
check("body: elderly note, phone, consent line, reply promise", "Note: 1 yatri 60 saal ya usse upar hain" in body
      and "Customer phone: 9876543210" in body and 'Customer consent: "Ye details hamare booking partner ko bheji jayengi."' in body
      and body.rstrip().endswith("Customer ko 2 ghante mein sampark ka bharosa diya gaya hai."), body)
with mock.patch.dict(os.environ, {"BOOKING_REPLY_HOURS": "4"}):
    check("BOOKING_REPLY_HOURS is used", "Customer ko 4 ghante mein" in M.build_message(M._row_dict(r0), {}, "a@x", "b@x").get_content())
check("the whole message encodes (UTF-8 bytes)", "रोशन".encode() in msg.as_bytes() or b"utf-8" in msg.as_bytes())

# ---------------- smtplib calls (STARTTLS, login, 10 s timeout, defaults)
fake = mock.MagicMock()
with mock.patch.object(smtplib, "SMTP", return_value=fake) as smtp_cls:
    fake.__enter__.return_value = fake
    M.smtp_send(msg, M._settings())
check("smtp: smtp.gmail.com:587 by default, timeout 10 s", smtp_cls.call_args.args == ("smtp.gmail.com", 587)
      and smtp_cls.call_args.kwargs.get("timeout") == 10, smtp_cls.call_args)
check("smtp: STARTTLS, then login with SMTP_USER, then one message", fake.starttls.called and fake.login.call_args.args
      == ("sender@example.com", "fake-smtp-pw") and fake.send_message.call_count == 1)

# ---------------- success
s1 = Sender()
check("success -> 'sent'", M.notify_request(no, send=s1, sleep=nap) == "sent" and len(s1.sent) == 1)
r1 = row(no)
check("success: notify_status sent, notified_at stored, no error", r1.notify_status == "sent" and r1.notified_at is not None
      and r1.notify_error is None)
check("never twice: a sent request is skipped", M.notify_request(no, send=s1, sleep=nap) == "skipped" and len(s1.sent) == 1)

# ---------------- auth failure: failed, the request is kept
tid2, no2 = make_request()
s2 = Sender(smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted for sender@example.com"),
            smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted for sender@example.com"))
naps.clear()
check("auth failure -> 'failed'", M.notify_request(no2, send=s2, sleep=nap) == "failed" and not s2.sent)
r2 = row(no2)
check("auth failure: notify_error 'auth' (class only), request still saved and open", r2.notify_status == "failed"
      and r2.notify_error == "auth" and r2.status == "new" and r2.notified_at is None)
check("a failed request is not retried again automatically", M.notify_request(no2, send=Sender(), sleep=nap) == "skipped")

# ---------------- timeout: one retry after ~30 s, then failed
tid3, no3 = make_request()
s3 = Sender(socket.timeout("timed out"), socket.timeout("timed out"), socket.timeout("timed out"))
naps.clear()
check("timeout twice -> 'failed' after exactly one retry", M.notify_request(no3, send=s3, sleep=nap) == "failed"
      and len(s3.errors) == 1 and naps == [30], (len(s3.errors), naps))
check("timeout: notify_error 'timeout'", row(no3).notify_error == "timeout")
tid4, no4 = make_request()
s4 = Sender(socket.timeout("timed out"))
naps.clear()
check("timeout then OK on the retry -> 'sent'", M.notify_request(no4, send=s4, sleep=nap) == "sent" and len(s4.sent) == 1
      and naps == [30] and row(no4).notify_error is None)

# ---------------- missing settings: failed 'config', no retry
tid5, no5 = make_request()
naps.clear()
with mock.patch.dict(os.environ, {"PARTNER_EMAIL": ""}):
    check("missing PARTNER_EMAIL -> failed 'config', no retry", M.notify_request(no5, send=Sender(), sleep=nap) == "failed"
          and row(no5).notify_error == "config" and naps == [])
check("error classes", [M.error_class(e) for e in (smtplib.SMTPAuthenticationError(535, b"x"), socket.timeout(), TimeoutError(),
      smtplib.SMTPRecipientsRefused({}), smtplib.SMTPServerDisconnected(), ConnectionRefusedError(), socket.gaierror(),
      smtplib.SMTPDataError(554, b"x"), ValueError())]
      == ["auth", "timeout", "timeout", "recipient", "connection", "connection", "connection", "smtp", "other"])

# ---------------- two senders at the same time: one email
tid6, no6 = make_request()
s6 = Sender()
barrier = threading.Barrier(4)


def race():
    barrier.wait()
    M.notify_request(no6, send=s6, sleep=nap)


ts = [threading.Thread(target=race) for _ in range(4)]
[t.start() for t in ts]
[t.join(10) for t in ts]
check("4 senders at once (two servers, double tap): exactly one email", len(s6.sent) == 1 and row(no6).notify_status == "sent",
      len(s6.sent))

# ---------------- the send never blocks the caller
tid7, no7 = make_request()
slow = lambda msg, cfg: time.sleep(1.5)  # noqa: E731
with mock.patch.object(M, "smtp_send", slow):
    t0 = time.perf_counter()
    th = M.send_in_background(no7)
    took = time.perf_counter() - t0
    check("send_in_background returns at once (< 0.2 s while SMTP takes 1.5 s)", took < 0.2 and row(no7).notify_status in ("pending", "sending"), took)
    th.join(10)
check("... and the background thread finishes as sent", row(no7).notify_status == "sent")

# ---------------- flag off: nothing sent, old wording
tid8, no8 = make_request(enabled=False)
check("flag off: notify_status 'off'", row(no8).notify_status == "off")
check("flag off: notify_request never sends an 'off' request", M.notify_request(no8, send=Sender(), sleep=nap) == "skipped")
with database.SessionLocal() as db:
    pub = BF._public(db.query(R).filter(R.request_no == no8).first())
check("flag off: the old wording, the test note, no notify line", BF.saved_text(pub, "hi") ==
      f"Aapki request save ho gayi hai: {no8}. Abhi ye test hai, partner ko nahi bheji gayi." and pub["notify"] == "off"
      and "notifyText" not in pub and BF.test_note("hi") == "Test version: kuch bheja nahi jayega")

# the whole flow through booking_flow.answer: flag off -> no thread; flag on -> one thread
starts = []
for enabled in (False, True):
    tid9 = make_trip()
    st = BF.BookingState(trip_id=tid9, adults=1, children=0, services=["hotel"], answers={"hotel_type": "budget", "hotel_rooms": 1},
                         travellers=[{"name": "Asha", "age": 30}], phone="9876543210", phone_ok=True)
    BF.save(redis_conn, UID, st)
    if enabled:
        os.environ["BOOKING_NOTIFY_ENABLED"] = "true"
    with mock.patch.object(M, "send_in_background", lambda n: starts.append(n)):
        s_, out = BF.answer(redis_conn, UID, tid9, "review", "yes")
    said = BF.saved_text(out.request, "hi")
    os.environ.pop("BOOKING_NOTIFY_ENABLED", None)
    redis_conn.delete(BF._key(UID, tid9))
    if not enabled:
        check("answer(): flag off -> saved, no email started, old wording", out.finished and not starts
              and "nahi bheji gayi" in said, said)
    else:
        check("answer(): flag on -> saved, one email started, 'bhej rahe hain'", out.finished and starts == [out.request["requestNo"]]
              and said.endswith("Partner ko bhej rahe hain."), (starts, said))

# ---------------- wording: sending / sent / failed (voice and screen use the same text)
tidp, nop = make_request()               # left pending: "sending"
os.environ["BOOKING_NOTIFY_ENABLED"] = "true"
X = "BR-1042"
check("wording hi: sending", BF.saved_text({"requestNo": X, "notify": "sending"}, "hi") == "Aapki request save ho gayi hai: BR-1042. Partner ko bhej rahe hain.")
check("wording hi: sent", BF.saved_text({"requestNo": X, "notify": "sent"}, "hi")
      == "Aapki request save ho gayi hai: BR-1042. Partner ko bhej di gayi hai, wo 2 ghante mein sampark karenge.")
check("wording hi: failed", BF.saved_text({"requestNo": X, "notify": "failed"}, "hi")
      == "Request save hai (BR-1042), par partner ko bhejna nahi ho paya. Hum dobara koshish karenge.")
check("wording en: sending / sent / failed", [BF.saved_text({"requestNo": X, "notify": n}, "en") for n in ("sending", "sent", "failed")]
      == ["Your request is saved: BR-1042. We are sending it to the partner.",
          "Your request is saved: BR-1042. It has been sent to the partner; they will contact you within 2 hours.",
          "Your request is saved (BR-1042), but sending it to the partner failed. We will try again."])
check("'bhej di' is never said before the email is sent", "bhej di" not in BF.saved_text({"requestNo": X, "notify": "sending"}, "hi")
      and "bhej di" not in BF.saved_text({"requestNo": X, "notify": "failed"}, "hi"))
lines = {}
for n in (no, no2, no3):                 # sent / failed(auth) / failed(timeout)
    with database.SessionLocal() as db:
        lines[n] = BF._public(db.query(R).filter(R.request_no == n).first())
with database.SessionLocal() as db:
    lines[nop] = BF._public(db.query(R).filter(R.request_no == nop).first())
check("status card: sending / sent / failed lines; the reply-time promise only once sent",
      lines[nop]["notify"] == "sending" and lines[nop]["notifyText"] == "Partner ko bhej rahe hain…"
      and lines[no]["notify"] == "sent" and lines[no]["notifyText"] == "Partner ko bhej di gayi hai, wo 2 ghante mein sampark karenge."
      and lines[no2]["notify"] == "failed" and "ghante" not in lines[no2]["notifyText"] and "ghante" not in lines[nop]["notifyText"],
      {k: v.get("notifyText") for k, v in lines.items()})
check("flag on: no 'Test version' note", BF.test_note("hi") is None)
with database.engine.begin() as c:
    c.execute(sql("UPDATE booking_requests SET status = 'contacted' WHERE request_no = :n"), {"n": no})
with database.SessionLocal() as db:
    contacted = BF._public(db.query(R).filter(R.request_no == no).first())
check("status card: no email line once the partner has contacted (status label only)", "notifyText" not in contacted)
os.environ.pop("BOOKING_NOTIFY_ENABLED")

# ---------------- logs
logs = log_buf.getvalue()
leaks = [w for w in ("रोशन", "Kamla", "Asha", "9876543210", "98765", "25 years", "68", "@example.com", "fake-smtp-pw",
                     "Username and Password", "Customer", "Kolkata", "IndiGo", "timed out") if w in logs]
check("logs: request_no / notify_status / error class only (no names, ages, phone, addresses, body, password)",
      not leaks and f"request={no} notify_status=sent" in logs and "error=auth" in logs and "error=timeout" in logs, leaks)

redis_conn.delete(BF._key(UID, "none"))
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
