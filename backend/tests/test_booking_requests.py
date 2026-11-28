"""
Booking stage 3 checks against a THROWAWAY LOCAL Postgres database (voyage_booking_ci), never Neon, never voice_test.
The local user/host come from VOICE_DEBUG_DATABASE_URL in backend/.env (the password is never printed); the script
aborts unless the host is localhost / 127.0.0.1. The database is created with all app tables (init_db) and dropped
at the end. Run from backend/: python -m tests.test_booking_requests
"""
import io
import logging
import os
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
LOCAL_HOSTS = ("localhost", "127.0.0.1")
CI_DB = "voyage_booking_ci"

# ---- safety first: only the local Postgres, decided BEFORE database/main are imported
_local = dotenv.dotenv_values(BACKEND_DIR / ".env").get("VOICE_DEBUG_DATABASE_URL")
from sqlalchemy.engine import make_url  # noqa: E402

if not _local:
    sys.exit("ABORT: VOICE_DEBUG_DATABASE_URL (the local Postgres) is not in backend/.env")
_base = make_url(_local)
if _base.host not in LOCAL_HOSTS:
    sys.exit(f"ABORT: host {_base.host!r} is not localhost/127.0.0.1")
CI_URL = _base.set(database=CI_DB)
print(f"database host={CI_URL.host} port={CI_URL.port} name={CI_URL.database}  (local only; password not shown)")
_PASSWORD = _base.password or ""

dotenv.load_dotenv = lambda *a, **k: None          # database.py must not load backend/.env (it points at Neon)
os.environ["DATABASE_URL"] = CI_URL.render_as_string(hide_password=False)
os.environ.pop("SKIP_BOOKING_TABLE_CREATE", None)
os.environ.pop("BOOKING_NOTIFY_ENABLED", None)
for _k in ("SMTP_HOST", "SMTP_PORT", "BOOKING_REPLY_HOURS"):
    os.environ.pop(_k, None)
os.environ.update({"SMTP_USER": "sender@example.com", "SMTP_PASSWORD": "fake-smtp-pw", "PARTNER_EMAIL": "partner@example.com"})
os.environ.pop("VOICE_DEBUG_STORE", None)
os.environ["AI_PROVIDER"] = "mock"
os.environ["OPENAI_API_KEY"] = "test-key-not-real"
os.environ["VOICE_TTS_ENABLED"] = "false"
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

from sqlalchemy import create_engine, text as sql  # noqa: E402
from sqlalchemy.exc import IntegrityError, OperationalError  # noqa: E402

_admin = create_engine(_base.set(database="postgres"), isolation_level="AUTOCOMMIT")
with _admin.connect() as c:
    c.execute(sql(f'DROP DATABASE IF EXISTS "{CI_DB}" WITH (FORCE)'))
    c.execute(sql(f'CREATE DATABASE "{CI_DB}"'))

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


def drop_ci():
    try:
        import database
        database.engine.dispose()
    except Exception:
        pass
    with _admin.connect() as c:
        c.execute(sql(f'DROP DATABASE IF EXISTS "{CI_DB}" WITH (FORCE)'))
    with _admin.connect() as c:
        gone = not c.execute(sql("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": CI_DB}).first()
    print(f"throwaway database {CI_DB} dropped: {gone}")


try:
    stdout_buf = io.StringIO()
    import database  # noqa: E402

    check("engine points at the local throwaway database", database.engine.url.host in LOCAL_HOSTS
          and database.engine.url.database == CI_DB, f"{database.engine.url.host}/{database.engine.url.database}")
    import main  # noqa: E402  (runs init_db on voyage_booking_ci)
    import booking_flow as BF  # noqa: E402
    import booking_mail  # noqa: E402
    import openai_client  # noqa: E402
    from fastapi.testclient import TestClient  # noqa: E402
    from models_booking import BookingRequestModel as R  # noqa: E402
    from models_db import AuthUserModel  # noqa: E402
    from models_trip import TripModel  # noqa: E402
    from redis_client import redis_conn  # noqa: E402
    from trip_lifecycle import today_ist  # noqa: E402
    from voice import agent, booking_voice as V  # noqa: E402

    for k in redis_conn.scan_iter("rl:*"):
        redis_conn.delete(k)

    log_buf = io.StringIO()
    _h = logging.StreamHandler(log_buf)
    for name in ("booking", "voice"):
        logging.getLogger(name).addHandler(_h)
        logging.getLogger(name).setLevel(logging.INFO)

    with database.engine.connect() as c:
        cols = [r[0] for r in c.execute(sql("SELECT column_name FROM information_schema.columns WHERE table_name = 'booking_requests' "
                                            "ORDER BY ordinal_position"))]
        idx = c.execute(sql("SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_booking_requests_open_trip'")).scalar()
        seq_start = c.execute(sql("SELECT start_value FROM pg_sequences WHERE sequencename = 'booking_request_no_seq'")).scalar()
    print("booking_requests columns:", ", ".join(cols))
    check("table created by init_db with every column", cols == ["id", "request_seq", "request_no", "trip_id", "user_id", "status",
          "services", "preferences", "travellers", "phone", "partner_note", "consent_text", "consented_at", "notify_status",
          "notified_at", "notify_error", "created_at", "updated_at"], cols)
    check("partial unique index on trip_id for open statuses", idx and "UNIQUE" in idx and "(trip_id)" in idx
          and "'new'" in idx and "'contacted'" in idx, idx)
    check("request numbers start at 1001 (sequence)", seq_start == 1001, seq_start)

    TODAY = today_ist()
    d = lambda n: (TODAY + timedelta(days=n)).isoformat()  # noqa: E731
    NOW = datetime.now(timezone.utc).isoformat()
    client = TestClient(main.app)
    client.__enter__()
    toks = {}
    for who in ("A", "B"):
        r = client.post("/api/auth/register", json={"name": f"Asha {who}k", "email": f"brq{who.lower()}_{uuid.uuid4().hex[:6]}@example.com",
                                                    "password": "secret123"})
        toks[who] = (r.json()["token"], r.json()["user"]["id"])
    client.cookies.clear()
    tok_a, uid_a = toks["A"]
    tok_b, uid_b = toks["B"]

    def make_trip(uid, adults=1, children=0):
        tid = f"trip_brq_{uuid.uuid4().hex[:8]}"
        trav = [{"id": f"a{i}", "type": "ADULT"} for i in range(adults)] + [{"id": f"c{i}", "type": "CHILD"} for i in range(children)]
        with database.SessionLocal() as db:
            db.add(TripModel(id=tid, user_id=uid, title="Goa", status="PLANNING", start_date=d(5), end_date=d(7), total_days=3,
                             destination={"name": "Goa"}, travelers=trav, budget={}, created_at=NOW, updated_at=NOW,
                             itinerary_status="READY"))
            db.commit()
        return tid

    T1, T2, T3, T4 = make_trip(uid_a), make_trip(uid_a, 2), make_trip(uid_a), make_trip(uid_a)

    def ws(token, action, payload):
        with client.websocket_connect("/ws/app") as sock:
            sock.send_json({"id": "x", "action": action, "payload": {**payload, "token": token}})
            while True:
                f = sock.receive_json()
                if f.get("id") == "x":
                    return f

    def wsd(action, trip, token=tok_a, **payload):
        f = ws(token, action, {"trip_id": trip, **payload})
        return f["data"] if f["status"] == 200 else {"_status": f["status"]}

    def ans(trip, value):
        q = wsd("booking:get", trip)["question"]
        return wsd("booking:answer", trip, question=q, value=value)

    def to_review(trip, ages=("75",), names=("Dadaji Sharma",)):
        wsd("booking:start", trip, services=["hotel"])
        ans(trip, "3star"); ans(trip, "2")
        for n_, a_ in zip(names, ages):
            ans(trip, n_); ans(trip, a_)
        ans(trip, "9876543210")
        return ans(trip, "yes")

    def rows(trip=None):
        with database.SessionLocal() as db:
            q = db.query(R)
            return q.filter(R.trip_id == trip).all() if trip else q.all()

    def key(uid, trip):
        return f"booking:flow:{uid}:{trip}"

    # ---------------- confirm creates one row
    v = to_review(T1)
    check("review reached", v["question"] == "review")
    v = ans(T1, "yes")
    rs = rows(T1)
    row = rs[0] if rs else None
    check("confirm: one row, BR-1001, status new, notify off (BOOKING_NOTIFY_ENABLED unset: nothing sent)", len(rs) == 1
          and row.request_no == "BR-1001" and row.request_seq == 1001 and row.status == "new" and row.notify_status == "off")
    check("confirm: the right values", row.user_id == uid_a and row.services == ["hotel"]
          and row.preferences == {"hotel_type": "3star", "hotel_rooms": 2} and row.travellers == [{"name": "Dadaji Sharma", "age": 75}]
          and row.phone == "9876543210" and row.partner_note == "1 yatri 60 saal ya usse upar hain; lift ya ground floor wala kamra dekhein."
          and row.consent_text == BF.CONSENT["en"] and row.consented_at is not None
          and row.created_at is not None and row.updated_at is not None)
    check("confirm: the Redis state is deleted", not redis_conn.exists(key(uid_a, T1)))
    check("screen reply (notify off): saved, test, NOT sent", v.get("finished") and v["message"] ==
          BF.SAVED["en"].format(no="BR-1001") and v["request"]["requestNo"] == "BR-1001")

    # ---------------- a second confirmation returns the same request
    s_again = BF.BookingState(trip_id=T1, adults=1, children=0, services=["train"], answers={}, phone="9123456789",
                              travellers=[{"name": "X Y", "age": 30}])
    req, created = BF.save_request(s_again, uid_a)
    check("second confirmation: the same request, no new row", req["requestNo"] == "BR-1001" and created is False and len(rows(T1)) == 1)
    v = wsd("booking:start", T1)
    check("screen start with an open request: no new flow, already saved", v["active"] is False
          and v["message"] == BF.ALREADY["en"].format(no="BR-1001") and not redis_conn.exists(key(uid_a, T1)))

    # two confirmations at the same time (double tap / voice + tap)
    st2 = BF.BookingState(trip_id=T2, adults=2, children=0, services=["hotel"], answers={"hotel_type": "any", "hotel_rooms": 1},
                          travellers=[{"name": "Ram", "age": 40}, {"name": "Sita", "age": 38}], phone="9876543210", phone_ok=True)
    barrier, got = threading.Barrier(2), []

    def confirm_now():
        barrier.wait()
        got.append(BF.save_request(st2, uid_a))

    threads = [threading.Thread(target=confirm_now) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    check("two concurrent confirmations: one row, both get the same number", len(rows(T2)) == 1 and len({g[0]["requestNo"] for g in got}) == 1
          and sorted(g[1] for g in got) == [False, True], got)
    # double tap through the screen: the second answer finds no flow and creates nothing
    v1 = to_review(T3)
    v1 = ans(T3, "yes")
    v2 = wsd("booking:answer", T3, question="review", value="yes")
    check("double tap: the second tap creates nothing", len(rows(T3)) == 1 and v2["active"] is False)

    # ---------------- the partial unique index
    def insert_direct(trip, status="new", uid=uid_a):
        with database.engine.begin() as c:
            n = c.execute(sql("SELECT nextval('booking_request_no_seq')")).scalar()
            c.execute(sql("""INSERT INTO booking_requests (id, request_seq, request_no, trip_id, user_id, status, services, preferences,
                             travellers, phone, consent_text, consented_at, created_at, updated_at)
                             VALUES (:id, :n, :no, :t, :u, :st, '[]', '{}', '[]', '9999999999', 'c', now(), now(), now())"""),
                      {"id": f"brq_{uuid.uuid4().hex[:12]}", "n": n, "no": f"BR-{n}", "t": trip, "u": uid, "st": status})

    try:
        insert_direct(T1)
        blocked = False
    except IntegrityError:
        blocked = True
    check("index: a second OPEN row for the trip is refused by the database", blocked and len(rows(T1)) == 1)
    try:
        insert_direct(T1, status="booked")
        closed_ok = True
    except IntegrityError:
        closed_ok = False
    check("index: closed rows (booked) don't count", closed_ok)
    with database.engine.begin() as c:
        c.execute(sql("UPDATE booking_requests SET status = 'cancelled' WHERE trip_id = :t AND status = 'new'"), {"t": T1})
    req, created = BF.save_request(s_again, uid_a)
    check("after cancelled: a new request is allowed (new number)", created and req["requestNo"] != "BR-1001" and req["status"] == "new")
    with database.engine.begin() as c:
        c.execute(sql("UPDATE booking_requests SET status = 'booked' WHERE trip_id = :t AND status = 'new'"), {"t": T1})
    req2, created2 = BF.save_request(s_again, uid_a)
    check("after booked: a new request is allowed", created2 and req2["requestNo"] not in ("BR-1001", req["requestNo"]))
    nos = [r_.request_no for r_ in rows()]
    check("request numbers are unique", len(nos) == len(set(nos)) and min(int(n[3:]) for n in nos) == 1001, sorted(nos))

    # ---------------- a database failure keeps everything
    v = to_review(T4)
    with mock.patch.object(BF, "save_request", side_effect=OperationalError("x", {}, Exception("db down"))):
        v = ans(T4, "yes")
    check("db failure (screen): retry message, still at the review, Redis state kept, no row",
          v.get("error") == "Request save nahi ho payi. Thodi der baad phir try kijiye." and v["question"] == "review"
          and redis_conn.exists(key(uid_a, T4)) and BF.load(redis_conn, uid_a, T4).phone == "9876543210" and not rows(T4))
    TRIP4 = agent.TripInfo(title="Goa", start_date=d(5), end_date=d(7), id=T4)
    CV = f"conv_brq_{uuid.uuid4().hex[:6]}"
    with mock.patch.object(openai_client, "chat_tools", lambda *a, **k: {"content": "x", "tool_calls": []}):
        r = agent.run_agent("book karwana hai", "hi", user_id=uid_a, conversation_id=CV, screen="/trip", trip=TRIP4, redis_conn=redis_conn)
        with mock.patch.object(BF, "save_request", side_effect=OperationalError("x", {}, Exception("db down"))):
            r = agent.run_agent("haan", "hi", user_id=uid_a, conversation_id=CV, screen="/trip", trip=TRIP4, redis_conn=redis_conn)
        check("db failure (voice): the retry message, state kept", r.reply_text == "Request save nahi ho payi. Thodi der baad phir try kijiye."
              and redis_conn.exists(key(uid_a, T4)), r.reply_text)
        # stage 4: notify on; SMTP is simulated (nothing leaves this machine), the thread is joined to see the end state
        sent_mail, threads = [], []
        real_bg = booking_mail.send_in_background

        def bg(no):
            t = real_bg(no)
            threads.append(t)
            return t
        os.environ["BOOKING_NOTIFY_ENABLED"] = "true"
        with mock.patch.object(booking_mail, "smtp_send", lambda msg, cfg: sent_mail.append(msg)),                 mock.patch.object(booking_mail, "send_in_background", bg):
            r = agent.run_agent("haan", "hi", user_id=uid_a, conversation_id=CV, screen="/trip", trip=TRIP4, redis_conn=redis_conn)
            for t in threads:
                t.join(10)
        no4 = rows(T4)[0].request_no if rows(T4) else None
        check("voice 'haan' again saves it; notify on -> 'Partner ko bhej rahe hain' (not yet 'bhej di')", r.reply_text ==
              f"Aapki request save ho gayi hai: {no4}. Partner ko bhej rahe hain." and not redis_conn.exists(key(uid_a, T4)), r.reply_text)
        row4 = rows(T4)[0]
        check("postgres: the email was sent once in the background -> notify_status sent, notified_at set",
              len(sent_mail) == 1 and row4.notify_status == "sent" and row4.notified_at is not None and row4.notify_error is None,
              (len(sent_mail), row4.notify_status))
        g = wsd("booking:get", T4)
        check("screen after sending: English confirmation and card line",
              g.get("message") == BF.SENT["en"].format(no=no4, hours=2)
              and g["request"]["notify"] == "sent" and g["request"]["notifyText"].startswith("Sent to the partner")
              and g.get("testNote") is None, g)
        check("postgres: a second send for the same request is skipped", booking_mail.notify_request(no4, send=lambda m, c: sent_mail.append(m))
              == "skipped" and len(sent_mail) == 1)
        os.environ.pop("BOOKING_NOTIFY_ENABLED")
        r = agent.run_agent("book karwana hai", "hi", user_id=uid_a, conversation_id=CV + "x", screen="/trip", trip=TRIP4, redis_conn=redis_conn)
        check("voice trigger with an open request: 'pehle se save hai', no new flow",
              r.reply_text == f"Aapki request {no4} pehle se save hai." and not redis_conn.exists(key(uid_a, T4)), r.reply_text)
        # notify on, screen
        with database.engine.begin() as c:
            c.execute(sql("UPDATE booking_requests SET status = 'cancelled' WHERE trip_id = :t"), {"t": T4})
        to_review(T4)
        os.environ["BOOKING_NOTIFY_ENABLED"] = "true"
        with mock.patch.object(booking_mail, "send_in_background", lambda no: None):   # left pending: "sending"
            v = ans(T4, "yes")
        os.environ.pop("BOOKING_NOTIFY_ENABLED")
        check("screen reply (notify on): sending status",
              v.get("finished") and v["message"].endswith("We are sending it to the partner.") and v["request"]["notify"] == "sending", v.get("message"))
        with database.engine.begin() as c:
            c.execute(sql("UPDATE booking_requests SET status = 'cancelled' WHERE trip_id = :t"), {"t": T4})
        to_review(T4)
        v = ans(T4, "yes")
        check("screen reply (notify off again): never claims it was sent", "was not sent to the partner" in v["message"])

        # ---------------- trip page status card
        labels = {}
        for st in ("new", "contacted", "booked", "cancelled"):
            with database.engine.begin() as c:
                c.execute(sql("UPDATE booking_requests SET status = :s WHERE trip_id = :t AND request_seq = "
                              "(SELECT max(request_seq) FROM booking_requests WHERE trip_id = :t)"), {"s": st, "t": T4})
            g = wsd("booking:get", T4)
            labels[st] = (g["request"]["statusLabel"], g["request"]["open"])
        check("status card labels", labels == {"new": ("Saved", True), "contacted": ("Partner contacted you", True),
                                               "booked": ("Booked", False), "cancelled": ("Cancelled", False)}, labels)

        # ---------------- another user / no login
        f = ws(tok_b, "booking:request", {"trip_id": T1})
        check("another user: WS booking:request refused", f["status"] == 404 and f["data"] is None)
        f = ws(tok_b, "booking:get", {"trip_id": T1})
        check("another user: WS booking:get refused", f["status"] == 404)
        H = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731
        check("another user: REST refused", client.get(f"/api/trips/{T1}/booking/request", headers=H(tok_b)).status_code == 404)
        check("no login: REST refused", client.get(f"/api/trips/{T1}/booking/request").status_code == 401)
        r_ = client.get(f"/api/trips/{T1}/booking/request", headers=H(tok_a))
        check("owner: REST read-only request (number + status, no personal data)", r_.status_code == 200
              and set(r_.json()["request"]) <= {"requestNo", "status", "statusLabel", "open", "createdAt", "notify", "notifyText"}, r_.json())
        r = agent.run_agent("book karwana hai", "hi", user_id=uid_b, conversation_id="conv_b", screen="/trip",
                            trip=agent.TripInfo(title="Goa", start_date=d(5), end_date=d(7), id=T1), redis_conn=redis_conn)
        check("another user: voice never hears A's request number", "BR-" not in r.reply_text, r.reply_text)

    # ---------------- cascades
    with database.SessionLocal() as db:
        db.query(TripModel).filter(TripModel.id == T3).delete()
        db.commit()
    check("deleting the trip removes its request (cascade)", not rows(T3))
    xid = f"usr_brqx_{uuid.uuid4().hex[:6]}"
    with database.SessionLocal() as db:
        db.add(AuthUserModel(id=xid, provider="test", provider_user_id=xid, created_at=NOW, last_login_at=NOW))
        db.commit()
    insert_direct(T2, status="cancelled", uid=xid)
    before = len([r_ for r_ in rows() if r_.user_id == xid])
    with database.engine.begin() as c:
        c.execute(sql("DELETE FROM auth_users WHERE id = :u"), {"u": xid})
    check("deleting the user removes their request (cascade)", before == 1 and not [r_ for r_ in rows() if r_.user_id == xid])

    # ---------------- logs
    logs = log_buf.getvalue()
    leaks = [w for w in ("Dadaji", "Sharma", "Ram", "Sita", "9876543210", "98765", "75 ", "lift ya ground") if w in logs]
    check("logs: no names, ages, phone numbers or the note", not leaks and "event=finish" in logs, leaks)
    check("logs: no password", not _PASSWORD or _PASSWORD not in logs)
    check("logs: the mail lines carry request_no and notify_status only", "[BOOKING MAIL] request=BR-" in logs
          and "notify_status=sent" in logs and "@example.com" not in logs and "fake-smtp-pw" not in logs)
    check("logs: a failed save logs only the error class", "event=request_save_failed" in logs and "error=OperationalError" in logs
          and "db down" not in logs)

    with database.engine.connect() as c:
        by_status = dict(c.execute(sql("SELECT status, count(*) FROM booking_requests GROUP BY status")).all())
    print(f"booking_requests rows by status (test data, no personal data printed): {by_status}")

    # ---------------- SKIP_BOOKING_TABLE_CREATE
    with database.engine.begin() as c:
        c.execute(sql("DROP TABLE booking_requests"))
    os.environ["SKIP_BOOKING_TABLE_CREATE"] = "true"
    database.init_db()
    with database.engine.connect() as c:
        absent = c.execute(sql("SELECT to_regclass('booking_requests')")).scalar() is None
        others = c.execute(sql("SELECT to_regclass('trips')")).scalar() is not None
    os.environ.pop("SKIP_BOOKING_TABLE_CREATE")
    database.init_db()
    with database.engine.connect() as c:
        back = c.execute(sql("SELECT to_regclass('booking_requests')")).scalar() is not None
        idx_back = c.execute(sql("SELECT 1 FROM pg_indexes WHERE indexname = 'uq_booking_requests_open_trip'")).scalar() == 1
    check("SKIP_BOOKING_TABLE_CREATE=true: init_db leaves booking_requests out (other tables fine)", absent and others)
    check("unset: init_db creates it again with its index", back and idx_back)
    # stage 4 columns on a table created before them: init_db adds them (ALTER ... ADD COLUMN IF NOT EXISTS)
    with database.engine.begin() as c:
        c.execute(sql("ALTER TABLE booking_requests DROP COLUMN notified_at, DROP COLUMN notify_error"))
    database.init_db()
    with database.engine.connect() as c:
        added = {r[0] for r in c.execute(sql("SELECT column_name FROM information_schema.columns WHERE table_name = 'booking_requests'"))}
    check("init_db adds notified_at / notify_error to an older booking_requests table", {"notified_at", "notify_error"} <= added)

    with database.engine.connect() as c:
        n_rows = c.execute(sql("SELECT count(*) FROM booking_requests")).scalar()
    print(f"booking_requests row count (after the SKIP test re-created it empty): {n_rows}")
    print(f"host used: {database.engine.url.host} / database: {database.engine.url.database}")
    client.__exit__(None, None, None)
    for uid in (uid_a, uid_b):
        for k in redis_conn.scan_iter(f"booking:flow:{uid}:*"):
            redis_conn.delete(k)
finally:
    drop_ci()

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if results and all(results) else 1)
