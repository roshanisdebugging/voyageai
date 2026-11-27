"""
Booking stage 4: email a saved booking request to the booking partner (one plain-text UTF-8 email).

Settings (backend/.env, never logged): SMTP_HOST (smtp.gmail.com), SMTP_PORT (587, STARTTLS), SMTP_USER (also the
From address), SMTP_PASSWORD, PARTNER_EMAIL (To), BOOKING_REPLY_HOURS (2), BOOKING_NOTIFY_ENABLED (false).

The request row is committed first (booking_flow.save_request); then send_in_background() starts a daemon thread,
so the voice reply and the screen never wait for SMTP. Sent at most once per request: the thread first claims the
row (notify_status pending -> sending, one UPDATE that only one caller can win), then ends it as sent (+ notified_at)
or failed (+ notify_error = a short class: auth / timeout / connection / recipient / smtp / config / other).
One automatic retry after RETRY_DELAY_S, then it stays failed.
Logs: request_no, notify_status and the error class only. Never names, ages, phone, addresses, the body or the password.
"""
import logging
import os
import smtplib
import socket
import ssl
import threading
import time
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, Dict, Optional

logger = logging.getLogger("booking")

SMTP_TIMEOUT_S = 10
RETRY_DELAY_S = 30
IST = timezone(timedelta(hours=5, minutes=30))


class MailConfigMissing(Exception):
    """SMTP_USER / SMTP_PASSWORD / PARTNER_EMAIL not set."""


def reply_hours() -> int:
    try:
        n = int(os.getenv("BOOKING_REPLY_HOURS", "2").strip())
        return n if 1 <= n <= 72 else 2
    except ValueError:
        return 2


def _settings() -> Dict[str, Any]:
    cfg = {"host": os.getenv("SMTP_HOST", "").strip() or "smtp.gmail.com",
           "port": os.getenv("SMTP_PORT", "").strip() or "587",
           "user": os.getenv("SMTP_USER", "").strip(), "password": os.getenv("SMTP_PASSWORD", ""),
           "to": os.getenv("PARTNER_EMAIL", "").strip()}
    try:
        cfg["port"] = int(cfg["port"])
    except ValueError:
        raise MailConfigMissing("SMTP_PORT")
    if not (cfg["user"] and cfg["password"] and cfg["to"]):
        raise MailConfigMissing("settings")
    return cfg


def error_class(err: BaseException) -> str:
    """A short, safe name for the failure (never the message text, which can quote addresses)."""
    if isinstance(err, MailConfigMissing):
        return "config"
    if isinstance(err, smtplib.SMTPAuthenticationError):
        return "auth"
    if isinstance(err, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(err, (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused)):
        return "recipient"
    if isinstance(err, (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, ConnectionError, socket.gaierror)):
        return "connection"
    if isinstance(err, smtplib.SMTPException):
        return "smtp"
    if isinstance(err, OSError):
        return "connection"
    return "other"


# ---------------- the email

def _nice_date(value: Any) -> str:
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d %b %Y")
    except ValueError:
        return str(value or "-")


def _ist(dt: Optional[datetime]) -> str:
    if dt is None:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).strftime("%d %b %Y, %H:%M IST")


def route_text(info: Dict[str, Any]) -> str:
    dest = info.get("destination") or "-"
    return f"{info['origin']} -> {dest}" if info.get("origin") else dest


def _value(v: Any) -> str:
    import booking_flow as BF
    if v == BF.ANY:
        return "Any (customer said: aap decide karo)"
    return BF._value_label(v, "en")


def build_message(req: Dict[str, Any], info: Dict[str, Any], sender: str, to: str, test: bool = False) -> EmailMessage:
    """req: the booking_requests row as a dict; info: {origin, destination, start_date, end_date}."""
    import booking_flow as BF
    tag = "[Cruiser TEST]" if test else "[Cruiser]"
    subject = f"{tag} Booking request {req['request_no']} | {route_text(info)} | {_nice_date(info.get('start_date'))}"
    lines = []
    if test:
        lines += ["TEST EMAIL - not a real customer. Please ignore.", ""]
    lines += [f"Booking request: {req['request_no']}",
              f"Created: {_ist(req.get('created_at'))}",
              f"Route: {route_text(info)}",
              f"Dates: {_nice_date(info.get('start_date'))} to {_nice_date(info.get('end_date'))}",
              ""]
    prefs = req.get("preferences") or {}
    for svc in req.get("services") or []:
        lines.append(f"{BF.LABELS['en'].get(svc, svc)}:")
        for q in BF.SERVICE_QUESTIONS.get(svc, []):
            if q in prefs:
                lines.append(f"  - {BF.CARD_LABELS['en'].get(q, q)}: {_value(prefs[q])}")
    lines += ["", "Travellers:"]
    for i, t in enumerate(req.get("travellers") or [], 1):
        lines.append(f"  {i}. {t.get('name') or '-'}, {t.get('age') if t.get('age') is not None else '-'} years")
    if req.get("partner_note"):
        lines += ["", f"Note: {req['partner_note']}"]
    lines += ["", f"Customer phone: {req.get('phone') or '-'}",
              f"Customer consent: \"{req.get('consent_text') or '-'}\" ({_ist(req.get('consented_at'))})",
              "",
              f"Customer ko {reply_hours()} ghante mein sampark ka bharosa diya gaya hai."]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content("\n".join(lines) + "\n", charset="utf-8")
    return msg


def smtp_send(msg: EmailMessage, cfg: Dict[str, Any]) -> None:
    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=SMTP_TIMEOUT_S) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        smtp.login(cfg["user"], cfg["password"])
        smtp.send_message(msg)


# ---------------- one request: claim, send (one retry), record

def _row_dict(row) -> Dict[str, Any]:
    return {c: getattr(row, c) for c in ("request_no", "created_at", "services", "preferences", "travellers",
                                         "phone", "partner_note", "consent_text", "consented_at")}


def _trip_info(db, trip_id: str) -> Dict[str, Any]:
    from models_place import CityModel
    from models_trip import TripModel
    trip = db.query(TripModel).filter(TripModel.id == trip_id).first()
    if trip is None:
        return {}
    origin = None
    if getattr(trip, "origin_city_id", None):
        city = db.query(CityModel).filter(CityModel.id == trip.origin_city_id).first()
        origin = city.name if city else None
    dest = trip.destination.get("name") if isinstance(trip.destination, dict) else None
    return {"origin": origin, "destination": dest or trip.title, "start_date": trip.start_date, "end_date": trip.end_date}


def _claim(db, request_no: str) -> bool:
    """pending -> sending in one UPDATE: only one caller (thread / process) can win, so one email per request."""
    from models_booking import BookingRequestModel as R
    n = (db.query(R).filter(R.request_no == request_no, R.notify_status == "pending")
         .update({R.notify_status: "sending", R.updated_at: datetime.now(timezone.utc)}, synchronize_session=False))
    db.commit()
    return n == 1


def _finish(db, request_no: str, status: str, error: Optional[str] = None) -> None:
    from models_booking import BookingRequestModel as R
    now = datetime.now(timezone.utc)
    values = {R.notify_status: status, R.updated_at: now, R.notify_error: error}
    if status == "sent":
        values[R.notified_at] = now
    db.query(R).filter(R.request_no == request_no).update(values, synchronize_session=False)
    db.commit()


def notify_request(request_no: str, send=None, sleep=None) -> str:
    """Send this request's email once. Returns the final notify_status ("sent" / "failed"), or "skipped" when
    it was not pending (already sent, being sent, failed or off)."""
    from database import SessionLocal
    from models_booking import BookingRequestModel as R
    send = send or smtp_send                    # looked up at call time (tests replace them)
    sleep = sleep or time.sleep
    db = SessionLocal()
    try:
        if not _claim(db, request_no):
            logger.info("[BOOKING MAIL] request=%s notify_status=skipped", request_no)
            return "skipped"
        row = db.query(R).filter(R.request_no == request_no).first()
        req, info = _row_dict(row), _trip_info(db, row.trip_id)
        err_class = "other"
        for attempt in (1, 2):
            try:
                cfg = _settings()
                send(build_message(req, info, cfg["user"], cfg["to"]), cfg)
                _finish(db, request_no, "sent")
                logger.info("[BOOKING MAIL] request=%s notify_status=sent attempt=%d", request_no, attempt)
                return "sent"
            except Exception as err:            # noqa: BLE001 - only the class is kept
                err_class = error_class(err)
                logger.warning("[BOOKING MAIL] request=%s attempt=%d error=%s", request_no, attempt, err_class)
                if attempt == 1 and err_class != "config":
                    sleep(RETRY_DELAY_S)
                else:
                    break
        _finish(db, request_no, "failed", err_class)
        logger.warning("[BOOKING MAIL] request=%s notify_status=failed error=%s", request_no, err_class)
        return "failed"
    except Exception as err:                    # noqa: BLE001 - a database problem: leave the row as it is
        logger.warning("[BOOKING MAIL] request=%s notify_status=error error=%s", request_no, type(err).__name__)
        return "error"
    finally:
        db.close()


def send_in_background(request_no: str) -> threading.Thread:
    """Never blocks the caller: the email goes from a daemon thread."""
    t = threading.Thread(target=notify_request, args=(request_no,), name=f"booking-mail-{request_no}", daemon=True)
    t.start()
    return t
