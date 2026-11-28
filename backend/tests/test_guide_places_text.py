"""
What the guide says about nearby places (guide_places.py) and how it is wired in (tour_guide_service.py).
No network, no Redis, no model: pure functions, plus the chat with Google, the model and the cost guard faked.
Run from backend/: python -m tests.test_guide_places_text      (--update rewrites the prompt snapshot)
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import dotenv

dotenv.load_dotenv = lambda *a, **k: None
os.environ.setdefault("DATABASE_URL", "postgresql://x:y@127.0.0.1:1/none")
os.environ["AI_PROVIDER"] = "mock"
os.environ.pop("TOURGUIDE_PRIMARY", None)

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

import guide_places as gp  # noqa: E402
import tour_guide_service as tg  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if (info != "" and not cond) else ""), flush=True)


def pl(name, dist, open_now=None, rating=None, count=None, primary="hospital", types=None, address=None):
    return {"name": name, "address": address, "lat": 26.9, "lng": 75.8, "distance_m": dist, "rating": rating,
            "rating_count": count, "open_now": open_now, "phone": "0141 222", "maps_url": None,
            "primary_type": primary, "types": types if types is not None else [primary, "health"]}


def found(category, places, label=None):
    return {"category": category, "status": "ok", "source": "named" if label else "device", "label": label, "places": places}


CAFES = found("cafe", [pl("Jaipur Vista Cafe", 66, True, 4.8, 552, "cafe"), pl("Chapter 1799", 65, True, 4.5, 17, "cafe")], "Hawa Mahal")
SHOPS = found("pharmacy", [pl("Chromwell Pharmacy", 50, True, primary="pharmacy"), pl("Apollo Pharmacy", 400, primary="pharmacy")])
HOSP = found("hospital", [pl("SMS Hospital", 1300, True, 4.2, 900), pl("City Care Hospital", 450, None), pl("Third Hospital", 600, None)])

# ---------------------------------------------------------------- 1. the check: what goes
DIRTY = [  # (category data, reply as seen in testing, what must be gone, what must stay)
    (SHOPS, "The nearest medical shop is Chromwell Pharmacy, 50 m away and open now. If you need delivery, consider using Blinkit or Swiggy Instamart.",
     ("Blinkit", "Swiggy", "Instamart", "delivery"), "The nearest medical shop is Chromwell Pharmacy, 50 m away and open now."),
    (HOSP, "SMS Hospital is 1.3 km away and open now. Dawai quick delivery apps se order kar sakte hain.",
     ("delivery",), "SMS Hospital is 1.3 km away and open now."),
    (CAFES, "Jaipur Vista Cafe is 66 m away and open now. It offers a premium experience. Best to visit early morning to avoid crowds.",
     ("premium", "crowds", "Best"), "Jaipur Vista Cafe is 66 m away and open now."),
    (HOSP, "SMS Hospital 1.3 km door hai. Yahan achha treatment milta hai! City Care Hospital 450 m door hai.",
     ("treatment",), "SMS Hospital 1.3 km door hai. City Care Hospital 450 m door hai."),
    (CAFES, "Chapter 1799 is 65 m away.\nIt gets crowded in the evening.", ("crowded",), "Chapter 1799 is 65 m away."),
    (SHOPS, "सबसे पास Chromwell Pharmacy है, 50 m दूर। आप ब्लिंकिट से भी मंगा सकते हैं।", ("ब्लिंकिट",), "सबसे पास Chromwell Pharmacy है, 50 m दूर।"),
    (HOSP, "Please dial 112 or 108 now. SMS Hospital is 1.3 km away, open now.", ("112",), "SMS Hospital is 1.3 km away, open now."),
]
for data, text, gone, stays in DIRTY:
    out, dropped = gp.clean_places_text(text, data, "near me")
    check(f"dropped: {gone}", dropped >= 1 and not any(g in out for g in gone) and out == stays, out)

for brand in ("Blinkit", "Swiggy", "Instamart", "Zepto", "Zomato", "Uber", "Ola", "Rapido", "Practo", "1mg", "PharmEasy", "Netmeds"):
    ok = brand in gp.BANNED_BRANDS
    for text in (f"Try {brand} for this.", f"try {brand.lower()}!", f"({brand.upper()})"):
        ok = ok and gp.is_banned(text)
    check(f"brand in the list and caught in any case: {brand}", ok)
for claim in ("a premium place", "luxury stay", "best treatment", "good treatment", "achha ilaaj", "accha treatment", "tasty food",
              "cheap food", "sasta khana", "a popular spot", "crowded in the evening", "bahut bheed hoti hai", "peak hours", "बहुत भीड़ होती है"):
    check(f"claim caught: {claim!r}", gp.is_banned(f"It is {claim}."))

# ---------------------------------------------------------------- 2. the check: what stays untouched
CLEAN = [
    (CAFES, "Near Hawa Mahal, Jaipur Vista Cafe is 66 m away, open now, rated 4.8 (552 reviews).  Chapter 1799 is 65 m away."),
    (HOSP, "Sabse paas SMS Hospital hai, 1.3 km door, aur abhi khula hai.\nDoosra option City Care Hospital hai, 450 m door."),
    (HOSP, "SMS Hospital 1.3 km door hai (4.2, 900 reviews)."),
    (SHOPS, "सबसे पास Chromwell Pharmacy है, 50 m दूर, अभी खुला है।"),
    (SHOPS, "Bolana mushkil hai, Chromwell Pharmacy 50 m away."),                       # 'ola' inside a word
    (CAFES, "Nothing here names a place at all."),
    (CAFES, ""),
]
for data, text in CLEAN:
    check(f"clean text unchanged: {text[:40]!r}", gp.clean_places_text(text, data, "x") == (text, 0))
odd = found("pharmacy", [pl("Premium Medical Store", 120, True, primary="pharmacy"), pl("Tata 1mg Store, MI Road", 300, primary="pharmacy")])
text = "Premium Medical Store is 120 m away and open now. Tata 1mg Store is 300 m away."
check("a banned word inside a real place name is fine", gp.clean_places_text(text, odd, "x") == (text, 0))
check("... but the claim itself is still dropped", gp.clean_places_text(text + " It is a premium shop.", odd, "x") == (text, 1))
split = gp.split_sentences("Dr. B. Lal Hospital is 1.3 km away. St. Mary's is 2 km away! Ok")
check("sentences: 'Dr.', initials, 'St.' and 1.3 don't end one", split == (["Dr. B. Lal Hospital is 1.3 km away. ", "St. Mary's is 2 km away! "], "Ok"), split)

# ---------------------------------------------------------------- 3. everything dropped -> the plain facts
out, n = gp.clean_places_text("SMS Hospital has the best treatment.", HOSP, "sabse paas hospital kahan hai?")
check("hospital: facts instead, first place with distance and one more", n == 1 and out
      == "SMS Hospital, 1.3 km away; open now. Another option: City Care Hospital, 450 m away; hours not available.", out)
out, _ = gp.clean_places_text("SMS Hospital is the best. City Care Hospital is 450 m away.", HOSP, "nearest hospital")
check("hospital: the nearest open one is never lost", out.startswith("SMS Hospital, 1.3 km away; open now."), out)
out, _ = gp.clean_places_text("एक बढ़िया कैफे है।", CAFES, "पास में कैफे कहाँ है")
check("Hindi question -> Hindi facts", out.startswith("Jaipur Vista Cafe, 66 m दूर; अभी खुला है।"), out)
check("facts never hold a rating, price or phone", not any(w in gp.facts_reply(CAFES, "x") for w in ("4.8", "0141", "₹")))

# ---------------------------------------------------------------- 4. streaming: the same check, sentence by sentence
text = DIRTY[0][1] + " Apollo Pharmacy is 400 m away."
for size in (1, 3, 7, 1000):
    gate = gp.PlaceSentenceGate(SHOPS)
    sent = [gate.feed(text[i:i + size]) for i in range(0, len(text), size)] + [gate.finish()]
    check(f"stream in pieces of {size}: banned sentence never sent, rest identical", "".join(sent)
          == "The nearest medical shop is Chromwell Pharmacy, 50 m away and open now. Apollo Pharmacy is 400 m away."
          and not any("Blink" in s for s in sent) and gate.dropped == 1, sent)
gate = gp.PlaceSentenceGate(CAFES)
check("stream: clean text arrives unchanged", "".join([gate.feed(c) for c in CLEAN[0][1]] + [gate.finish()]) == CLEAN[0][1])

# ---------------------------------------------------------------- 5. prompt snapshot and block
snap = BACKEND_DIR / "tests" / "snapshots" / "guide_places_prompt.txt"
prompt = gp.places_system_prompt("hospital")
if "--update" in sys.argv:
    snap.write_text(prompt, encoding="utf-8", newline="\n")
check("prompt snapshot unchanged (--update after a deliberate change)", snap.read_text(encoding="utf-8") == prompt)
flat = " ".join(prompt.split())
for needle in ("ONLY these facts from the block: name, distance, open status, rating together with its review count, address",
               "Mention a rating only if its review count is >= 20", "price, or words like premium, cheap, luxury",
               "quality: best, good treatment, tasty", "crowd or timing predictions",
               "delivery apps, or any brand, app or website that is not in the block", "medical advice",
               "2-3 short sentences in clear English", "Name ONLY places listed in the VERIFIED PLACES block",
               "the nearest open hospital) by name and distance", "at most one more option",
               "No delivery apps, no treatment claims, no advice about medicines"):
    check(f"prompt says: {needle[:50]}", needle in flat)
check("the prompt itself names no brand", not any(b in prompt for b in gp.BANNED_BRANDS))
check("emergency rules only for hospitals", "EMERGENCY RULES" in prompt and "EMERGENCY RULES" not in gp.places_system_prompt("cafe"))
block = gp.places_block(CAFES)
check("block: rating with >= 20 reviews, hidden below", "rating: 4.8 (552 reviews)" in block and "4.5" not in block
      and "too few reviews" in block, block)
edge = gp.places_block(found("cafe", [pl("A", 1, rating=4.1, count=20), pl("B", 2, rating=3.9, count=19)]))
check("block: exactly 20 shown, 19 not", "4.1 (20 reviews)" in edge and "3.9" not in edge, edge)
block = gp.places_block(found("hospital", [pl("SMS", 1, address="JLN Marg")] + HOSP["places"]))
check("block: address yes, phone no, hospital max two", "address: JLN Marg" in block and "0141" not in block
      and block.count("open now:") == 2, block)

# ---------------------------------------------------------------- 6. which results count, and their order
MIXED = [pl("Keshav Medical Hall", 100, True, primary="pharmacy", types=["pharmacy", "hospital", "health", "store"]),
         pl("Closed Hospital", 150, False), pl("Near Unknown Hospital", 200, None), pl("Far Open Hospital", 2000, True),
         pl("Near Open Hospital", 900, True), pl("Far Unknown Hospital", 700, None)]
out, n = gp.filter_and_sort("hospital", MIXED)
check("hospital: pharmacy removed", "Keshav Medical Hall" not in [p["name"] for p in out] and n == 5)
check("hospital: open by distance, unknown by distance, closed last", [p["name"] for p in out] == [
    "Near Open Hospital", "Far Open Hospital", "Near Unknown Hospital", "Far Unknown Hospital", "Closed Hospital"])
out, n = gp.filter_and_sort("hospital", [MIXED[0], MIXED[2]])
check("only 1 hospital left: the pharmacy stays, after it (even though it is open and nearer)",
      [p["name"] for p in out] == ["Near Unknown Hospital", "Keshav Medical Hall"] and n == 1 and out[1]["_shop"] is True)
out, n = gp.filter_and_sort("hospital", [MIXED[0], MIXED[2], MIXED[1]])
check("2 hospitals left: no pharmacy", len(out) == 2 and not any(p["_shop"] for p in out))
for t in ("hospital", "doctor", "clinic", "health"):
    check(f"hospital intent keeps type {t}", gp.filter_and_sort("hospital", [pl("X", 1, primary="service", types=[t])])[1] == 1)
check("hospital intent drops an unrelated type", gp.filter_and_sort("hospital", [pl("X", 1, primary="bank", types=["bank"])]) == ([], 0))
drug = [pl("D", 1, primary="drugstore"), pl("H1", 5), pl("H2", 6)]
check("drugstore counts as a pharmacy", [p["name"] for p in gp.filter_and_sort("hospital", drug)[0]] == ["H1", "H2"])
real = pl("Harsh Medical & General Store", 283, True, 4.0, 12, "medical_center", ["medical_center", "hospital", "health"])
out, _ = gp.filter_and_sort("hospital", [real, pl("H1", 400), pl("H2", 500)])
check("a shop Google files as medical_center + hospital goes too (seen live)", [p["name"] for p in out] == ["H1", "H2"])
check("... but 'City Hospital & Medical Store' stays a hospital",
      gp.filter_and_sort("hospital", [pl("City Hospital & Medical Store", 1)])[1] == 1)
out, _ = gp.filter_and_sort("pharmacy", [pl("Hosp", 10, primary="hospital", types=["hospital", "pharmacy"]),
                                         pl("Plain Hospital", 20), pl("B Chemist", 300, primary="pharmacy"),
                                         pl("A Drug", 100, True, primary="drugstore"),
                                         pl("Homeo Store", 50, primary="health", types=["pharmacy", "health", "store"])])
check("pharmacy intent: hospitals out, by distance", [p["name"] for p in out] == ["Homeo Store", "A Drug", "B Chemist"], out)
# Full hospitals before dispensaries and clinics (real results around Hawa Mahal, 25 Nov 2026, plus SMS).
LIVE = [pl("Rehan Khan, Dental technician", 183, None, 5, 1), pl("Govt. Disp. Sirhdyodi Jaipur", 265, True, 4, 2),
        pl("Rajasthan Rajya Sahkari Upbhokta Sandh", 267, True, 5, 2, "medical_center", ["medical_center", "hospital"]),
        pl("Government homoeopathy dispensary", 270, False, 5, 2), pl("Dr Rajeev Jain", 320, False, 4.3, 12, "doctor"),
        pl("Dental Hospital", 390, True, 4.8, 6), pl("K K Diagnostic Centre", 422, True, 4.5, 8, "medical_clinic"),
        pl("Shri Mukund Chikitsalya", 427, None, 5, 10), pl("SMS Hospital", 1900, True, 4.1, 5000), pl("Closed Hospital", 500, False)]
out, _ = gp.filter_and_sort("hospital", LIVE)
check("full hospitals first (open, unknown), then the rest (open, unknown), closed last", [p["name"] for p in out] == [
    "SMS Hospital", "Shri Mukund Chikitsalya", "Govt. Disp. Sirhdyodi Jaipur", "Rajasthan Rajya Sahkari Upbhokta Sandh",
    "Dental Hospital", "K K Diagnostic Centre", "Rehan Khan, Dental technician", "Closed Hospital",
    "Government homoeopathy dispensary", "Dr Rajeev Jain"], [p["name"] for p in out])
for name, count, full in (("SMS Hospital", 0, True), ("Fortis Escorts", 800, True), ("Mittal bhavan", None, False),
                          ("साकेत हॉस्पिटल", None, True), ("Healing Angel Clinic & Nursing Home", 30, True),
                          ("Shri Radhe hospital and diagnostic centre", 1, True), ("City Dispensary", 900, False)):
    check(f"full hospital? {name} ({count} reviews) -> {full}", gp.is_full_hospital(pl(name, 1, count=count)) is full)

check("cards get no internal fields", not set(gp.public_place(out[0])) & set(gp.INTERNAL_FIELDS))

# ---------------------------------------------------------------- 7. wired into the chat
google = {"answers": [], "radii": []}


async def fake_nearby(lat, lng, radius=0, place_types=None, *, strict=False, counter=None, max_results=5):
    google["radii"].append(radius)
    google["max"] = max_results
    rows = google["answers"].pop(0)
    if counter is not None:
        counter.add()
    return [{"name": r["name"], "address": "JLN Marg", "latitude": lat + r["distance_m"] / 111195, "longitude": lng,
             "rating": r["rating"], "userRatingCount": r["rating_count"] or 0, "open_now": r["open_now"], "phone": "0141 222",
             "maps_uri": None, "primary_type": r["primary_type"], "types": r["types"]} for r in rows]


from services import google_maps_service as gms  # noqa: E402

gms.search_nearby_places = fake_nearby
tg._cache_get = lambda key: None
tg._cache_set = lambda *a: None
tg._save_exchange = lambda *a, **k: None
tg.evaluate_cost_guards = lambda m: (True, tg.ESSENTIAL_GATE, "")
model = {"text": "", "system": ""}


def fake_stream(prompt, system_prompt, temperature=0.4):
    model["system"] = system_prompt
    if model["text"] is None:
        raise RuntimeError("down")
    for i in range(0, len(model["text"]), 5):
        yield model["text"][i:i + 5]


tg._openai_stream = fake_stream
tg._gemini_chain = lambda *a, **k: (model.get("gemini"), False)


def ask(msg, answers, text):
    google.update(answers=list(answers), radii=[])
    model["text"] = text
    return tg.process_concierge_message("u", msg, lat=26.9, lng=75.8, recent_history=[], device_lat=26.9, device_lng=75.8)


def stream(msg, answers, text):
    google.update(answers=list(answers), radii=[])
    model["text"] = text

    async def go():
        return [c async for c in tg.stream_concierge_events("u", msg, lat=26.9, lng=75.8, recent_history=[],
                                                            device_lat=26.9, device_lng=75.8)]
    ev = [(c.split("\n", 1)[0][7:], json.loads(c.split("data: ", 1)[1])) for c in asyncio.run(go())]
    return "".join(d["t"] for n, d in ev if n == "token"), ev[-1][1]


BAD = ("SMS Hospital is 1.3 km away and open now. Yahan achha treatment milta hai. Dawai Blinkit se mangwa lijiye."
       "<<<CHIPS:[\"Quick Delivery\"]>>>")
H2 = [pl("City Care Hospital", 450, None), pl("SMS Hospital", 1300, True, 5.0, 2), pl("Keshav Medical Hall", 80, True, primary="pharmacy")]
want = "In an emergency, call 112 or 108. SMS Hospital is 1.3 km away and open now."
out = ask("sabse paas hospital kahan hai?", [H2], BAD)
check("JSON reply: 112/108 line, the facts, nothing else", out["reply"] == want, out["reply"])
check("JSON cards: open first, pharmacy gone, one Google call", [p["name"] for p in out["places"]] == ["SMS Hospital", "City Care Hospital"]
      and google["radii"] == [3000] and out["emergency"] is True)
check("hospital: 10 asked", google["max"] == 10)
out = ask("nearest hospital", [[pl(f"H{i} Hospital", 100 + i) for i in range(10)]], "H0 Hospital is 100 m away.")
check("hospital: 10 found, the best 5 shown", [p["name"] for p in out["places"]] == [f"H{i} Hospital" for i in range(5)])
out = ask("sabse paas hospital kahan hai?", [H2], BAD)
check("chips come from code (a question the app can answer)", out["chips"] == ["Medical shop near me"]
      and tg.detect_place_intent(out["chips"][0])["category"] == "pharmacy", out["chips"])
check("the model got the places prompt, not the general one", model["system"] == gp.places_system_prompt("hospital"))
shown, done = stream("sabse paas hospital kahan hai?", [H2], BAD)
check("stream: the banned sentences were never shown, done agrees", shown.strip() == want and done["reply"] == want, (shown, done["reply"]))
model["gemini"] = BAD
shown, done = stream("sabse paas hospital kahan hai?", [H2], None)
check("stream through Gemini: checked too", shown.strip() == want and done["reply"] == want and done["provider"] == "gemini", shown)
model["gemini"] = None
out = ask("medical shop near me", [[pl("Chromwell Pharmacy", 50, True, primary="pharmacy")]], None)
check("pharmacy: 5 asked", google["max"] == 5)
check("no model answered: the facts, never a delivery app", out["error"] == "LLM_TOTAL_FAILURE"
      and out["reply"] == "Chromwell Pharmacy, 50 m away; open now." and "Blinkit" not in json.dumps(out), out["reply"])
out = ask("nearest hospital", [H2], None)
check("no model answered, hospital: 112/108 first", out["reply"].startswith("In an emergency, call 112 or 108. SMS Hospital"), out["reply"])
out = ask("nearest hospital", [[H2[2]], [pl("Far Hospital", 6000, True)]], "Far Hospital is 6.0 km away.")
check("only a medical shop in 3 km: one look at 10 km finds the hospital", google["radii"] == [3000, 10000]
      and [p["name"] for p in out["places"]] == ["Far Hospital"], out["places"])
out = ask("nearest hospital", [[H2[2]], [H2[2]]], "Keshav Medical Hall, a medical shop, is 80 m away.")
check("nothing else at 10 km either: the shop as a last resort", [p["name"] for p in out["places"]] == ["Keshav Medical Hall"]
      and "_shop" not in out["places"][0] and "types" not in out["places"][0], out["places"])
for label, msg in (("Restaurants near Hawa Mahal", "cafe"), ("Cafes near Hawa Mahal", "restaurant")):
    chip = gp.place_chips(found(msg, [], "Hawa Mahal"))[0]
    check(f"chip {chip!r} is a place question", chip == label and tg.detect_place_intent(chip)["place_text"] == "Hawa Mahal", tg.detect_place_intent(chip))

print(f"\n{sum(results)}/{len(results)} passed", flush=True)
sys.exit(0 if all(results) else 1)
