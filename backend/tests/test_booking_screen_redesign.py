"""Booking screen regression checks with an isolated in-memory draft store."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import booking_flow as booking


class DraftStore:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, ttl, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class BookingScreenTests(unittest.TestCase):
    def setUp(self):
        self.store = DraftStore()
        self.trip = SimpleNamespace(id="sample-trip")
        self.state = booking.BookingState(self.trip.id, 1, 1, services=["flight", "hotel"])
        booking._reset_travellers(self.state)
        booking.save(self.store, "sample-user", self.state)

    def answer(self, question, value):
        return booking.screen_action(
            self.store, None, "sample-user", self.trip, "booking:answer",
            {"question": question, "value": value},
        )

    def fill_preferences(self):
        self.assertEqual(self.answer("flight_time", "24:00–07:00")["errorCode"], "choice_invalid")
        self.assertEqual(self.answer("flight_time", "08:00–08:00")["errorCode"], "choice_invalid")
        flight = self.answer("flight_time", "22:30–02:00")
        self.assertEqual(flight["question"], "flight_airline")
        self.assertIn("+1 day", next(row["value"] for row in flight["card"]["rows"] if row["key"] == "flight_time"))
        self.assertEqual(self.answer("flight_airline", "IndiGo")["question"], "hotel_type")
        self.assertEqual(self.answer("hotel_type", "rating:6")["errorCode"], "choice_invalid")
        self.assertEqual(self.answer("hotel_type", "rating:5")["question"], "hotel_rooms")
        return self.answer("hotel_rooms", "2")

    def test_combined_details_are_atomic_and_reviewable(self):
        details = self.fill_preferences()["travelDetails"]
        self.assertEqual([person["isChild"] for person in details["travelers"]], [False, True])
        payload = {
            "travellers": [{"name": "Sample Traveler", "age": "30"}, {"name": "Guest Traveler", "age": "20"}],
            "phone": "9876500000",
        }
        mismatch = self.answer("traveler_details", payload)
        self.assertEqual(mismatch["errorCode"], "age_mismatch")
        self.assertEqual(mismatch["travelDetails"], details)
        self.assertEqual(self.answer("traveler_details", {**payload, "phone": []})["errorCode"], "phone_invalid")
        self.assertEqual(self.answer("traveler_details", {**payload, "travellers": [17]})["errorCode"], "stale")
        review = self.answer("traveler_details", {**payload, "confirmAgeMismatch": True})
        self.assertEqual(review["question"], "review")
        self.assertTrue(any("5 stars" in row["text"] for row in review["summary"]))
        self.assertEqual(review["travelDetails"]["phone"], "9876500000")
        edited = self.answer("traveler_details", {**payload, "phone": "9876500001", "confirmAgeMismatch": True})
        self.assertEqual(edited["question"], "review")
        self.assertEqual(edited["travelDetails"]["phone"], "9876500001")

        with patch.object(booking, "save_request", return_value=({"requestNo": "BR-TEST", "notify": "off"}, True)) as save:
            self.assertTrue(self.answer("review", "yes")["finished"])
            submitted = save.call_args.args[0]
            self.assertEqual(submitted.answers["flight_time"], "22:30–02:00")
            self.assertEqual(submitted.answers["hotel_type"], "rating:5")
            self.assertEqual(submitted.phone, "9876500001")
        self.assertEqual(booking._value_label("22:30–02:00", "en"), "22:30–02:00 (+1 day)")

    def test_back_to_previous_service_from_phone_step(self):
        self.fill_preferences()
        for qid, value in [
            ("t0_name", "Sample Traveler"), ("t0_age", "30"),
            ("t1_name", "Guest Traveler"), ("t1_age", "12"),
        ]:
            self.answer(qid, value)
        back = self.answer("traveler_details_back", "")
        self.assertEqual(back["question"], "hotel_rooms")
        resumed = self.answer("hotel_rooms", "3")
        self.assertEqual(resumed["question"], "phone")
        self.assertEqual(resumed["travelDetails"]["travelers"][0]["name"], "Sample Traveler")

    def test_train_windows_and_flexible_hotel_rating(self):
        self.state.services = ["train", "hotel"]
        booking.save(self.store, "sample-user", self.state)
        self.answer("train_class", "3A")
        self.assertEqual(self.answer("train_time", "06:00–10:30")["question"], "train_tatkal")
        self.answer("train_tatkal", "no")
        self.assertEqual(self.answer("hotel_type", booking.ANY)["question"], "hotel_rooms")
        state = booking.load(self.store, "sample-user", self.trip.id)
        self.assertEqual(state.answers["hotel_type"], booking.ANY)

    def test_legacy_voice_questions_still_work(self):
        screen = booking.screen_action(self.store, None, "sample-user", self.trip, "booking:get", {})
        self.assertEqual(screen["choices"][0]["label"], "Morning")
        self.assertIn("Flight kis time chahiye?", booking.prompt_for(self.state, "flight_time", "hi"))
        self.assertEqual(self.answer("flight_time", "morning")["question"], "flight_airline")
        self.answer("flight_airline", "cheapest")
        self.assertEqual(self.answer("hotel_type", "4plus")["question"], "hotel_rooms")
        self.answer("hotel_rooms", "any")
        for qid, value in [
            ("t0_name", "Sample Traveler"), ("t0_age", "30"),
            ("t1_name", "Guest Traveler"), ("t1_age", "12"), ("phone", "9876500000"),
        ]:
            self.answer(qid, value)
        self.assertEqual(self.answer("phone_ok", "yes")["question"], "review")


if __name__ == "__main__":
    unittest.main()
