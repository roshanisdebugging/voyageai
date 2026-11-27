"""
Booking stage 4, manual check: send ONE clearly marked dummy booking email to PARTNER_EMAIL with the real SMTP
settings from backend/.env (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, PARTNER_EMAIL).

    python -m scripts.send_test_booking_mail

Subject "[Cruiser TEST] Booking request BR-TEST | ...", a made-up traveller and phone 9000000000.
Prints only "sent" or the error class (auth / timeout / connection / recipient / smtp / config / other).
Never prints a setting, an address or the password. Does not touch the database (no import of database / main).
It sends even when BOOKING_NOTIFY_ENABLED is false: running it IS the request to send one test email.
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BACKEND, ".env"), override=True)
    import booking_mail

    now = datetime.now(timezone.utc)
    start = date.today() + timedelta(days=10)
    req = {"request_no": "BR-TEST", "created_at": now, "services": ["train", "hotel"],
           "preferences": {"train_class": "3A", "train_time": "morning", "train_tatkal": "no",
                           "hotel_type": "3star", "hotel_rooms": 1},
           "travellers": [{"name": "Test Yatri (dummy)", "age": 30}, {"name": "परीक्षण यात्री", "age": 65}],
           "phone": "9000000000",
           "partner_note": "TEST: 1 yatri 60 saal ya usse upar hain; lift ya ground floor wala kamra dekhein.",
           "consent_text": "Ye details hamare booking partner ko bheji jayengi.", "consented_at": now}
    info = {"origin": "Kolkata", "destination": "Goa", "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=3)).isoformat()}
    try:
        cfg = booking_mail._settings()
        booking_mail.smtp_send(booking_mail.build_message(req, info, cfg["user"], cfg["to"], test=True), cfg)
    except Exception as err:      # noqa: BLE001 - only the class is printed
        print(booking_mail.error_class(err))
        return 1
    print("sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
