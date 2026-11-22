```Your users and their languages:
VoyageAI is a voice-first travel planner for Indian travellers aged 18 to 60. They plan trips on a phone, often one-handed, in a cab, at a station or in a market, and many dislike typing or long forms. They speak Hindi, English, or Hinglish (Hindi and English mixed in one sentence), with strong regional accents such as Bhojpuri, Punjabi, Tamil or Bengali influence. Place names are Indian and easy to mishear: Varanasi, Amer Fort, Charminar.

The voice flow, step by step:
Build a mobile-first web app with one small floating mic button on every page after login. No wake word, no separate voice mode.
1. The user taps the mic once to start and taps again to stop. It auto-stops at 30 seconds. A pulsing animation shows that the app is listening.
2. The browser streams 16 kHz mono audio to the backend over a WebSocket.
3. Speech-to-text converts it to text. Use Whisper, with Wispr Flow as a swappable provider.
4. An AI agent with tools proposes exactly one action: open a page, answer a travel question, find a place on the map, read the weather, or collect trip details. The model only proposes. Backend code checks and decides.
5. The app performs the action (navigates, focuses the map) and speaks a short reply.
Example: "Taj Mahal kahan hai?" then "Map par dikhaun?" then "haan" and the map opens on it.
Creating a trip: the agent asks for one missing detail at a time (destination, dates, adults and children, budget). Code decides what is missing, not the model. It reads the dates back in words ("15 December se 18 December, teen raat") and waits for "haan" or a correction. Then it opens a pre-filled review page. Nothing is saved until the user taps Proceed or says "haan".

What the product says or shows back:
- Replies are at most two short sentences, in the user's language, spoken in a natural Indian-accent voice. The transcript is not shown by default.
- Small actions (open a page, mark an activity done, save a place) happen at once with a 5-second Undo button.
- Big actions (create a trip, add an expense, regenerate the plan) first read back a summary and wait for "haan" or a Confirm tap.
- Voice never deletes anything. It says: "Trip delete karne ke liye button khud dabaiye, dhyan se."
- Never invent facts. Opening hours, prices and fees come only from a verified source. Otherwise say: "Abhi pakki jaankari nahi mil rahi."
- A small on-screen note, "Details badal sakti hain", is shown but not spoken.

Noise, accents, mixed languages and misheard input:
- Hinglish in one sentence is normal input. Choose the reply voice from the reply text: Hindi or Hinglish gets a Hindi voice, plain English gets an English voice.
- Misheard place names: search Indian places and the user's own trips. When unsure, ask a short choice ("Taj Mahal ya Taj Hotel?") and never guess.
- Garbled or empty speech: say "Samajh nahi aaya, phir se boliye." and take no action.
- Clips shorter than half a second or only noise are ignored with "Zara paas se boliye."
- Off-topic requests (jokes, cricket): "Main sirf aapki trip mein madad kar sakta hoon."
- Never change data from a doubtful transcript. Always confirm first.
- If speech-to-text, the AI or the voice service fails or is rate limited, show a friendly message and speak a fallback line. The next tap must still work. Never stay silent.
- Limit each user to 15 voice turns per minute.

Prototype scope:
This is a real, working app, not a mock. Real trips, itineraries and places are loaded from the user's own account after login. Pages: Map, Itinerary, Food and Settings, each reachable by voice. Include the floating mic, the reply bubble, the Undo toast and the Confirm card. For demo purposes, a signed-in test user may have two trips, one in Goa and one in Jaipur.
```