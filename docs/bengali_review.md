# Bengali (beta): strings for a native speaker to review

These Bengali texts were written by us (Claude), **not checked by a native speaker**. Please correct anything that
sounds unnatural. The register is spoken, polite (আপনি). `{...}` are placeholders filled by the app (names, dates,
numbers): keep them exactly. Rows marked **??** are wording we were unsure of.
On-screen labels (booking buttons and card, trip status lines, consent text, the map panel title) stay English
for Bengali and are not listed. Generated from the source (`voice/*.py`, `booking_flow.py`, `tour_guide_service.py`).

## The 25 most-heard

| id | English | Bengali |
|---|---|---|
| `voice/draft.py:QUESTIONS[destination]` | Where do you want to go? | কোথায় যেতে চান? |
| `voice/draft.py:QUESTIONS[start_date]` | From which date to which date? | কোন তারিখ থেকে কোন তারিখ পর্যন্ত যাবেন? |
| `voice/draft.py:QUESTIONS[adults]` | How many adults are going? | কতজন প্রাপ্তবয়স্ক যাচ্ছেন? |
| `voice/draft.py:QUESTIONS[children]` | Any children coming along? | সঙ্গে কোনো বাচ্চা আছে? |
| `voice/draft.py:QUESTIONS[budget_inr]` | What's the total budget? | মোট বাজেট কত? |
| `voice/draft.py:QUESTIONS[origin_city]` | Where are you starting from? | কোথা থেকে যাবেন? |
| `voice/draft.py:QUESTIONS[purpose]` | What's the trip for? A holiday, work or business, an event like a hackathon, a pilgrimage, or something else? | ?? কী কাজে যাচ্ছেন? বেড়াতে, অফিসের কাজে বা বিজনেসে, হ্যাকাথনের মতো কোনো ইভেন্টে, তীর্থে, নাকি অন্য কিছু? |
| `voice/draft.py:READBACK_FROM` | {frm} to {to}, {start} to {end}, {nights}, {who}{why}. Is that right? | {frm} থেকে {to}, {start} থেকে {end}, {nights}, {who}{why}। ঠিক আছে? |
| `voice/draft.py:READBACK` | {start} to {end}, {nights}{why}. Is that right? | {start} থেকে {end}, {nights}{why}। ঠিক আছে? |
| `voice/agent.py:READY_REPLY` | All details are on the review page. Check them and tap Proceed, or say yes. | সব তথ্য রিভিউ পেজে আছে। দেখে নিয়ে Proceed চাপুন, অথবা হ্যাঁ বলুন। |
| `voice/agent.py:CONFIRMED_REPLY` | Creating your trip. | আপনার ট্রিপ বানাচ্ছি। |
| `voice/agent.py:CANCELLED_REPLY` | Okay, no trip was created. Nothing was saved. | ঠিক আছে, ট্রিপ বানানো হলো না। কিছু সেভ হয়নি। |
| `booking_flow.py:PROMPTS[services]` | Flight, train or hotel? Pick one or more. | ট্রেন, ফ্লাইট নাকি হোটেল বুক করবেন? এক বা একাধিক বেছে নিন। |
| `booking_flow.py:PROMPTS[hotel_type]` | What kind of hotel? Budget, 3-star or 4-star and above? | কেমন হোটেল চাই? বাজেট, 3-star নাকি 4-star বা তার উপরে? |
| `booking_flow.py:PROMPTS[hotel_rooms]` | How many rooms? 1 to 9. | কয়টা রুম লাগবে? 1 থেকে 9। |
| `booking_flow.py:PROMPTS[name_adult]` | Traveller {n}'s name? | যাত্রী {n}-এর নাম? |
| `booking_flow.py:PROMPTS[age]` | How old is {name}? | {name}-এর বয়স কত? |
| `booking_flow.py:PROMPTS[phone]` | Please give one mobile number, 10 digits. | একটা মোবাইল নম্বর বলুন, 10 সংখ্যার। |
| `booking_flow.py:PROMPTS[phone_ok]` | Number: {digits}. Is that right? | নম্বর: {digits}। ঠিক আছে? |
| `booking_flow.py:PROMPTS[review]` | Is that right? | ঠিক আছে? |
| `booking_flow.py:SAVED` | Your request is saved: {no}. This is a test for now; it was not sent to the partner. | আপনার অনুরোধ সেভ হয়েছে: {no}। এখন এটা পরীক্ষামূলক, পার্টনারের কাছে পাঠানো হয়নি। |
| `voice/agent.py:UNCLEAR_REPLY` | Samajh nahi aaya, phir se boliye. | বুঝতে পারলাম না, আবার বলুন। |
| `voice/agent.py:ACK_REPLY` | Okay. | ঠিক আছে। |
| `voice/agent.py:TRY_LATER_REPLY` | I can't answer right now, please try again in a little while. | এখন উত্তর দিতে পারছি না, একটু পরে আবার চেষ্টা করুন। |
| `voice/booking_voice.py:UNCLEAR` | I didn't get that. | বুঝতে পারলাম না। |

## Trip questions and the read-back

| id | English | Bengali |
|---|---|---|
| `voice/agent.py:DATE_AGAIN` | Okay, from which date to which date? | ঠিক আছে, কোন তারিখ থেকে কোন তারিখ পর্যন্ত? |
| `voice/agent.py:DAYS_LENGTH` | , {n} days | , {n} দিন |
| `voice/agent.py:NOTHING_TO_CONFIRM` | There's nothing to confirm right now. | এখন কনফার্ম করার মতো কিছু নেই। |
| `voice/agent.py:ORIGIN_SKIPPED` | Okay, without a starting city. | ঠিক আছে, কোথা থেকে যাচ্ছেন সেটা ছাড়াই। |
| `voice/agent.py:PLAN_ACCEPTED` | Okay, we'll start from the checked plan. | ?? ঠিক আছে, যাচাই করা প্ল্যান দিয়েই বানাচ্ছি। |
| `voice/agent.py:PLAN_DECLINED` | Okay. | ঠিক আছে। |
| `voice/agent.py:PLAN_OFFER` | There's a checked plan for {name}. Shall we start with it? | ?? {name}-এর একটা যাচাই করা প্ল্যান আছে। ওটা দিয়ে শুরু করব? |
| `voice/agent.py:REPLACED_NOTE` | I dropped the previous trip draft. | আগের ট্রিপের খসড়াটা বাদ দিলাম। |
| `voice/draft.py:<inline>#1` | From which date? | কোন তারিখ থেকে? |
| `voice/draft.py:AREA_GIVE_UP` | I couldn't find {name} either, so we'll go on without an area. | {name}-ও খুঁজে পেলাম না, এলাকা ছাড়াই এগোচ্ছি। |
| `voice/draft.py:AREA_RETRY` | I couldn't find {name} near {city}. Say the area again, or say skip? | {city}-এর কাছে {name} খুঁজে পেলাম না। এলাকার নামটা আবার বলবেন, নাকি স্কিপ করবেন? |
| `voice/draft.py:NEAR_AREA` | , near {area} | , {area}-এর কাছে |
| `voice/draft.py:ORIGIN_CHECK` | Starting from {name}? Is that right? | {name} থেকে যাচ্ছেন? ঠিক আছে? |
| `voice/draft.py:ORIGIN_GIVE_UP` | I couldn't find {name} either, so we'll go on without a starting city. | {name}-ও খুঁজে পেলাম না, কোথা থেকে যাচ্ছেন সেটা ছাড়াই এগোচ্ছি। |
| `voice/draft.py:ORIGIN_RETRY` | I couldn't find {name}. Say it again, or say skip? | {name} খুঁজে পেলাম না। আবার বলবেন, নাকি স্কিপ করবেন? |
| `voice/draft.py:ORIGIN_SAME` | Starting from {name} and going to {name}? Is that right? | {name} থেকে {name}-এই যাচ্ছেন? ঠিক আছে? |
| `voice/draft.py:OWN_PURPOSE` | for your {text} | ?? আপনার {text}-এর জন্য |
| `voice/draft.py:PROBLEMS[adults_min]` | At least one adult must travel. | অন্তত একজন প্রাপ্তবয়স্ক থাকতে হবে। |
| `voice/draft.py:PROBLEMS[budget_min]` | The budget must be at least ₹{n:,}. | বাজেট অন্তত ₹{n:,} হতে হবে। |
| `voice/draft.py:PROBLEMS[budget_unclear]` | I didn't get the budget. | বাজেটটা বুঝতে পারলাম না। |
| `voice/draft.py:PROBLEMS[children_unclear]` | I didn't get the number of children. | বাচ্চাদের সংখ্যাটা বুঝতে পারলাম না। |
| `voice/draft.py:PROBLEMS[date_unclear]` | I didn't get the date. | তারিখটা বুঝতে পারলাম না। |
| `voice/draft.py:PROBLEMS[days_range]` | A trip can be 1 to 30 days. | ট্রিপ 1 থেকে 30 দিনের হতে পারে। |
| `voice/draft.py:PROBLEMS[end_before_start]` | The end date is before the start date. | ফেরার তারিখটা যাওয়ার তারিখের আগে পড়ছে। |
| `voice/draft.py:PROBLEMS[past_date]` | That date has passed. Please say a future date. | এই তারিখটা পেরিয়ে গেছে। সামনের কোনো তারিখ বলুন। |
| `voice/draft.py:PROBLEMS[place_not_found]` | I couldn't find {name} in India. Which place? | ভারতে {name} খুঁজে পেলাম না। কোন জায়গা? |
| `voice/draft.py:PROBLEMS[start_first]` | Please tell me the start date first. | আগে যাওয়ার তারিখটা বলুন। |
| `voice/draft.py:PROBLEMS[too_far_ahead]` | Trips can start at most a year ahead. | এক বছরের বেশি পরের ট্রিপ এখন বানানো যাবে না। |
| `voice/draft.py:PROBLEMS[too_long]` | A trip can be at most 30 days. | ট্রিপ সর্বোচ্চ 30 দিনের হতে পারে। |
| `voice/draft.py:PROBLEMS[too_many]` | A trip can have at most {n} travelers. | একটা ট্রিপে সর্বোচ্চ {n} জন যেতে পারেন। |
| `voice/draft.py:PURPOSE_SKIPPED` |  |  |
| `voice/draft.py:PURPOSE_WORDS[business]` | for work | কাজের জন্য |
| `voice/draft.py:PURPOSE_WORDS[event]` | for an event | ইভেন্টের জন্য |
| `voice/draft.py:PURPOSE_WORDS[leisure]` | for a holiday | বেড়ানোর জন্য |
| `voice/draft.py:PURPOSE_WORDS[other]` | for the reason you gave | আপনার বলা কারণে |
| `voice/draft.py:PURPOSE_WORDS[pilgrimage]` | for a pilgrimage | তীর্থের জন্য |
| `voice/draft.py:QUESTIONS[base_area]` | Which area will you mostly be in? For example Electronic City. | কোন এলাকায় বেশি থাকবেন বা কাজ করবেন? যেমন Electronic City। |
| `voice/draft.py:QUESTIONS[end_date]` | Until which date? | কোন তারিখ পর্যন্ত ট্রিপ? |
| `voice/draft.py:SUMMARY` | {dest}{origin}, {start} to {end}, {who}, budget ₹{budget:,}. Confirm saves what's on the review page. A trip can't be undone by voice. | ?? {dest}{origin}, {start} থেকে {end}, {who}, বাজেট ₹{budget:,}। Confirm চাপলে রিভিউ পেজের তথ্য সেভ হবে। ভয়েস দিয়ে ট্রিপ আর ফেরানো যাবে না। |

## Booking (flight, train, hotel)

| id | English | Bengali |
|---|---|---|
| `booking_flow.py:ALREADY` | Your request {no} is already saved. | আপনার অনুরোধ {no} আগে থেকেই সেভ করা আছে। |
| `booking_flow.py:CANCELLED` | Okay. | ঠিক আছে। |
| `booking_flow.py:DONE` | This is a test for now. Nothing was sent. | এখন এটা পরীক্ষামূলক। কিছু পাঠানো হয়নি। |
| `booking_flow.py:ERRORS[age_invalid]` | Please give an age as a whole number from 0 to 110. | বয়সটা 0 থেকে 110-এর মধ্যে একটা পূর্ণ সংখ্যায় বলুন। |
| `booking_flow.py:ERRORS[airline_invalid]` | Please say the airline's name in letters only. | এয়ারলাইনের নামটা শুধু অক্ষরে বলুন। |
| `booking_flow.py:ERRORS[airline_name_needed]` | Which airline? | কোন এয়ারলাইন? |
| `booking_flow.py:ERRORS[airline_script]` | Please write the airline's name in English or Hindi. | এয়ারলাইনের নামটা ইংরেজি, হিন্দি বা বাংলায় লিখুন। |
| `booking_flow.py:ERRORS[choice_invalid]` | I didn't get that. | বুঝতে পারলাম না। |
| `booking_flow.py:ERRORS[decide_not_allowed]` | I need this one from you. | এটা আপনাকেই বলতে হবে। |
| `booking_flow.py:ERRORS[name_invalid]` | A name can only have letters, 2 to 60 of them. | নামে শুধু অক্ষর থাকতে পারে, 2 থেকে 60টা। |
| `booking_flow.py:ERRORS[name_script]` | Please write the name in English or Hindi. | নামটা ইংরেজি, হিন্দি বা বাংলায় লিখুন। |
| `booking_flow.py:ERRORS[no_travellers]` | This trip has no travellers. | এই ট্রিপে কোনো যাত্রী নেই। |
| `booking_flow.py:ERRORS[phone_invalid]` | That number doesn't look right. Please give a 10-digit mobile number starting with 6, 7, 8 or 9. | নম্বরটা ঠিক মনে হচ্ছে না। 6, 7, 8 বা 9 দিয়ে শুরু হওয়া 10 সংখ্যার মোবাইল নম্বর বলুন। |
| `booking_flow.py:ERRORS[rooms_invalid]` | Rooms can be 1 to 9. | রুম 1 থেকে 9টা হতে পারে। |
| `booking_flow.py:ERRORS[save_failed]` | The request couldn't be saved. Please try again in a little while. | অনুরোধটা সেভ করা গেল না। একটু পরে আবার চেষ্টা করুন। |
| `booking_flow.py:ERRORS[services_empty]` | Pick at least one: flight, train or hotel. | অন্তত একটা বেছে নিন: ফ্লাইট, ট্রেন বা হোটেল। |
| `booking_flow.py:ERRORS[stale]` | This question has changed. | এই প্রশ্নটা বদলে গেছে। |
| `booking_flow.py:ERRORS[trip_past]` | This trip is already over. | এই ট্রিপ শেষ হয়ে গেছে। |
| `booking_flow.py:PROMPTS[age_adult_check]` | {name} is {age}? This is an adult's place. Is that right? | {name}-এর বয়স {age}? এটা বড়দের জায়গা। ঠিক আছে? |
| `booking_flow.py:PROMPTS[age_child_check]` | {name} is {age}? This is a child's place. Is that right? | {name}-এর বয়স {age}? এটা বাচ্চার জায়গা। ঠিক আছে? |
| `booking_flow.py:PROMPTS[change]` | What should I change? Flight, train, hotel, travellers or phone? | কী বদলাতে হবে? ফ্লাইট, ট্রেন, হোটেল, যাত্রী নাকি ফোন? |
| `booking_flow.py:PROMPTS[flight_airline]` | Any particular airline, or the cheapest? | কোনো নির্দিষ্ট এয়ারলাইন, নাকি যেটা সবচেয়ে সস্তা? |
| `booking_flow.py:PROMPTS[flight_time]` | What time for the flight? Morning, afternoon, evening or night? | ফ্লাইট কখন চাই? সকাল, দুপুর, সন্ধ্যা নাকি রাত? |
| `booking_flow.py:PROMPTS[name_child]` | Child {n}'s name? | বাচ্চা {n}-এর নাম? |
| `booking_flow.py:PROMPTS[review_screen]` | Please check the details. | সব তথ্য দেখে নিন। |
| `booking_flow.py:PROMPTS[train_class]` | Which train class? Sleeper, 3AC, 2AC or 1AC? | ট্রেনে কোন ক্লাস? স্লিপার, 3AC, 2AC নাকি 1AC? |
| `booking_flow.py:PROMPTS[train_tatkal]` | Is Tatkal okay? | ?? তৎকাল চলবে? |
| `booking_flow.py:PROMPTS[train_time]` | What time for the train? Morning, afternoon, evening or night? | ট্রেন কখন চাই? সকাল, দুপুর, সন্ধ্যা নাকি রাত? |
| `booking_flow.py:PROMPTS[travellers_intro]` | Now the travellers' names and ages. | এবার যাত্রীদের নাম আর বয়স। |
| `booking_flow.py:SENDING` | Your request is saved: {no}. We are sending it to the partner. | আপনার অনুরোধ সেভ হয়েছে: {no}। পার্টনারের কাছে পাঠাচ্ছি। |
| `booking_flow.py:SEND_FAILED` | Your request is saved ({no}), but sending it to the partner failed. We will try again. | অনুরোধ সেভ হয়েছে ({no}), কিন্তু পার্টনারের কাছে পাঠানো যায়নি। আমরা আবার চেষ্টা করব। |
| `booking_flow.py:SENT` | Your request is saved: {no}. It has been sent to the partner; they will contact you within {hours} hours. | আপনার অনুরোধ সেভ হয়েছে: {no}। পার্টনারের কাছে পাঠানো হয়েছে, ওঁরা {hours} ঘণ্টার মধ্যে যোগাযোগ করবেন। |
| `booking_flow.py:_SPOKEN[1A]` | 1AC | 1AC |
| `booking_flow.py:_SPOKEN[2A]` | 2AC | 2AC |
| `booking_flow.py:_SPOKEN[3A]` | 3AC | 3AC |
| `booking_flow.py:_SPOKEN[3star]` | 3-star | 3-star |
| `booking_flow.py:_SPOKEN[4plus]` | 4-star or above | 4-star বা তার উপরে |
| `booking_flow.py:_SPOKEN[ANY]` | any | ?? যেটা পাওয়া যায় |
| `booking_flow.py:_SPOKEN[SL]` | sleeper | স্লিপার |
| `booking_flow.py:_SPOKEN[afternoon]` | afternoon | দুপুর |
| `booking_flow.py:_SPOKEN[budget]` | budget | বাজেট |
| `booking_flow.py:_SPOKEN[cheapest]` | cheapest | সবচেয়ে সস্তা |
| `booking_flow.py:_SPOKEN[consent]` | Details go to our booking partner. | তথ্য আমাদের বুকিং পার্টনারের কাছে যাবে। |
| `booking_flow.py:_SPOKEN[evening]` | evening | সন্ধ্যা |
| `booking_flow.py:_SPOKEN[morning]` | morning | সকাল |
| `booking_flow.py:_SPOKEN[night]` | night | রাত |
| `booking_flow.py:_SPOKEN[room]` | room | রুম |
| `booking_flow.py:_SPOKEN[rooms]` | rooms | রুম |
| `booking_flow.py:_SPOKEN[tatkal_no]` | no Tatkal | তৎকাল নয় |
| `booking_flow.py:_SPOKEN[tatkal_yes]` | Tatkal okay | তৎকাল চলবে |
| `booking_flow.py:_SPOKEN[traveller]` | traveller | ?? জন যাত্রী |
| `booking_flow.py:_SPOKEN[travellers]` | travellers | ?? জন যাত্রী |
| `voice/booking_voice.py:AGE_GUESS` | Is the age {age}? Is that right? | বয়স {age}? ঠিক আছে? |
| `voice/booking_voice.py:AIRLINE_ASK` | {name} airline? Is that right? | {name} এয়ারলাইন? ঠিক আছে? |
| `voice/booking_voice.py:DECIDE_OFFER` | Shall I take it as 'you decide'? | ?? তাহলে কি 'আপনিই ঠিক করুন' ধরে নেব? |
| `voice/booking_voice.py:NAME_UNCLEAR` | I didn't get the name. Please say it again, or type it on the screen. | নামটা বুঝতে পারলাম না। আবার বলুন, অথবা স্ক্রিনে টাইপ করে দিন। |
| `voice/booking_voice.py:NO_TRIP` | Please open a trip first. | আগে একটা ট্রিপ খুলুন। |
| `voice/booking_voice.py:RESUMED` | Continuing the booking: | ?? বুকিং আগের জায়গা থেকে: |
| `voice/booking_voice.py:SAY_NAME` | Please say the correct name. | সঠিক নামটা বলুন। |
| `voice/booking_voice.py:SCREEN_HINT` | You can also tap a button on the screen. | স্ক্রিনের বোতামও চাপতে পারেন। |
| `voice/booking_voice.py:TYPE_HINT` | You can also type it on the screen. | স্ক্রিনে টাইপও করতে পারেন। |
| `voice/booking_voice.py:TYPE_ONLY` | Please type it on the screen. | স্ক্রিনে টাইপ করে দিন। |

## Errors and fixed lines

| id | English | Bengali |
|---|---|---|
| `tour_guide_service.py:VOICE_DECLINE` | I can only help with your trip. | আমি শুধু আপনার ট্রিপের ব্যাপারে সাহায্য করতে পারি। |
| `tour_guide_service.py:VOICE_LANG_RULE` | Reply in simple English. | Reply in natural, simple spoken Bengali written in Bangla script. |
| `tour_guide_service.py:VOICE_NO_FACTS` | I couldn't find reliable info right now. | এখন নির্ভরযোগ্য তথ্য পাওয়া যাচ্ছে না। |
| `voice/agent.py:ANSWER_FAILED` | I couldn't get an answer right now, please ask again in a moment. | এখন উত্তর পাওয়া গেল না, একটু পরে আবার জিজ্ঞেস করুন। |
| `voice/agent.py:DECLINE_REPLY` | I can only help with your trip. | আমি শুধু আপনার ট্রিপের ব্যাপারে সাহায্য করতে পারি। |
| `voice/agent.py:DELETE_REPLY` | To delete a trip, please tap the delete button yourself, carefully. | ট্রিপ মুছতে হলে ডিলিট বোতামটা নিজে সাবধানে চাপুন। |
| `voice/agent.py:EDIT_UNSUPPORTED_REPLY` | I can't change an existing trip by voice yet. You can edit it on the trip screen with Swap or Optimize Day, add a place from the map with Add to Itinerary, or I can plan a new trip. | ?? ভয়েস দিয়ে এখনো তৈরি ট্রিপ বদলানো যায় না। ট্রিপ স্ক্রিনে Swap বা Optimize Day দিয়ে বদলাতে পারেন, ম্যাপ থেকে Add to Itinerary দিয়ে জায়গা যোগ করতে পারেন, নয়তো আমি নতুন ট্রিপ বানাতে পারি। |
| `voice/agent.py:FALLBACK_BY_LANG` | FALLBACK_REPLY_EN | FALLBACK_REPLY_BN |
| `voice/agent.py:NOTHING_CHANGED` | Okay, nothing changed. | ঠিক আছে, কিছু বদলানো হয়নি। |
| `voice/agent.py:OK_NO_REPLY` | Okay. | ঠিক আছে। |
| `voice/agent.py:result#1` | Showing {name} on the map. | {name} ম্যাপে দেখাচ্ছি। |
| `voice/pipeline.py:EMPTY_BY_LANG` | EMPTY_TRANSCRIPT_REPLY_EN | EMPTY_TRANSCRIPT_REPLY_BN |

## Page and tool replies (pages, map, weather, trips, actions, plan changes)

| id | English | Bengali |
|---|---|---|
| `voice/pages.py:CONFIRM[expenses]` | Opened your expenses. | আপনার খরচের হিসাব খুলে দিলাম। |
| `voice/pages.py:CONFIRM[explore]` | Opened explore. | এক্সপ্লোর খুলে দিলাম। |
| `voice/pages.py:CONFIRM[food]` | Opened food places. | খাবারের জায়গাগুলো খুলে দিলাম। |
| `voice/pages.py:CONFIRM[guide]` | Opened the tour guide. | ট্যুর গাইড খুলে দিলাম। |
| `voice/pages.py:CONFIRM[home]` | Opened home. | হোম খুলে দিলাম। |
| `voice/pages.py:CONFIRM[itinerary]` | Opened your itinerary. | ?? আপনার ইটিনেরারি খুলে দিলাম। |
| `voice/pages.py:CONFIRM[itinerary_day]` | Opened day {n}. | {n} নম্বর দিন খুলে দিলাম। |
| `voice/pages.py:CONFIRM[map]` | Opened the map. | ম্যাপ খুলে দিলাম। |
| `voice/pages.py:CONFIRM[more]` | Opened more options. | সেটিংস খুলে দিলাম। |
| `voice/pages.py:CONFIRM[my_trips]` | Opened your trips. | আপনার ট্রিপগুলো খুলে দিলাম। |
| `voice/pages.py:CONFIRM[plan_trip]` | Opened a new trip. | নতুন ট্রিপের পেজ খুলে দিলাম। |
| `voice/pages.py:CONFIRM[rides]` | Opened rides. | ?? রাইডস খুলে দিলাম। |
| `voice/pages.py:CONFIRM[saved_places]` | Opened your saved places. | আপনার সেভ করা জায়গাগুলো খুলে দিলাম। |
| `voice/pages.py:CONFIRM[trip]` | Opened your trip. | আপনার ট্রিপ খুলে দিলাম। |
| `voice/pages.py:NO_TRIP_REPLY` | No trip is open, opening your trips. | এখন কোনো ট্রিপ খোলা নেই, আপনার ট্রিপগুলো খুলছি। |
| `voice/pages.py:WHICH_PAGE_REPLY` | Which page should I open? | কোন পেজ খুলব? |
| `voice/tools/actions.py:<inline>#1` | {name} is already saved. | {name} আগে থেকেই সেভ করা আছে। |
| `voice/tools/actions.py:<inline>#2` | Which one: {names}? | কোনটা: {names}? |
| `voice/tools/actions.py:ASK_WHICH` | Which one: {names}? | কোনটা: {names}? |
| `voice/tools/actions.py:CATEGORY_WORD[food]` | food | খাবার |
| `voice/tools/actions.py:CATEGORY_WORD[other]` | other | অন্যান্য |
| `voice/tools/actions.py:CATEGORY_WORD[shopping]` | shopping | কেনাকাটা |
| `voice/tools/actions.py:CATEGORY_WORD[stay]` | stay | ?? থাকা |
| `voice/tools/actions.py:CATEGORY_WORD[tickets]` | tickets | টিকিট |
| `voice/tools/actions.py:CATEGORY_WORD[transport]` | transport | যাতায়াত |
| `voice/tools/actions.py:DAY_TAG` | {title} (day {n}) | {title} ({n} নম্বর দিন) |
| `voice/tools/actions.py:T[bad_amount]` | How much was it, in rupees? | কত টাকা খরচ হয়েছিল? |
| `voice/tools/actions.py:T[failed]` | That didn't work, please try again. | এটা হলো না, আবার চেষ্টা করুন। |
| `voice/tools/actions.py:T[gone]` | That trip isn't available any more; nothing changed. | এই ট্রিপটা আর পাওয়া যাচ্ছে না, কিছু বদলানো হয়নি। |
| `voice/tools/actions.py:T[no_activity_named]` | Which activity? | কোন অ্যাক্টিভিটি? |
| `voice/tools/actions.py:T[no_itinerary]` | This trip's itinerary isn't ready yet. | এই ট্রিপের ইটিনেরারি এখনো তৈরি হয়নি। |
| `voice/tools/actions.py:T[no_place]` | Which place? Search for it or open it first, then say save. | কোন জায়গা? আগে জায়গাটা খুঁজুন বা খুলুন, তারপর সেভ বলুন। |
| `voice/tools/actions.py:T[no_trip]` | Which trip? | কোন ট্রিপে? |
| `voice/tools/actions.py:T[not_saved]` | That place isn't saved. | এই জায়গাটা সেভ করা নেই। |
| `voice/tools/actions.py:T[rate_limited]` | Too many requests right now, please try again in a bit. | এখন অনেক বেশি অনুরোধ এসেছে, একটু পরে আবার বলুন। |
| `voice/tools/actions.py:T[regen_ask]` | Rebuild the whole itinerary? It will take a little time. | পুরো ইটিনেরারি আবার বানাব? একটু সময় লাগবে। |
| `voice/tools/actions.py:T[regen_busy]` | The itinerary is already being rebuilt, please wait. | ইটিনেরারি আগে থেকেই তৈরি হচ্ছে, একটু অপেক্ষা করুন। |
| `voice/tools/actions.py:T[regen_done]` | Rebuilding the itinerary. I'll tell you when it's ready. | ইটিনেরারি আবার বানাচ্ছি। তৈরি হলে জানিয়ে দেব। |
| `voice/tools/actions.py:T[trip_changed]` | A different trip is open now, so nothing changed. Please say it again. | এখন অন্য একটা ট্রিপ খোলা আছে, তাই কিছু বদলানো হয়নি। আবার বলুন। |
| `voice/tools/actions.py:T[which_activity]` | Which activity? I couldn't find that name in the itinerary. | কোন অ্যাক্টিভিটি? এই নামটা ইটিনেরারিতে পেলাম না। |
| `voice/tools/actions.py:summary#1` | Add ₹{amount:,} for {title} under {word} to your {trip_label(ctx)} trip? | ?? আপনার {trip_label(ctx)} ট্রিপে {word} খাতে {title}-এর জন্য ₹{amount:,} যোগ করব? |
| `voice/tools/actions.py:summary#2` | Add ₹{amount:,} for {title} under {word}? | ?? {word} খাতে {title}-এর জন্য ₹{amount:,} যোগ করব? |
| `voice/tools/actions.py:summary#3` | Rebuild your {trip_label(ctx)} trip's whole itinerary? It will take a little time. | আপনার {trip_label(ctx)} ট্রিপের পুরো ইটিনেরারি আবার বানাব? একটু সময় লাগবে। |
| `voice/tools/actions.py:text#1` | {where}marked {act.title} as done. | ?? {where}{act.title} হয়ে গেছে বলে চিহ্নিত করলাম। |
| `voice/tools/actions.py:text#2` | {where}{act.title} is no longer marked done. | ?? {where}{act.title} থেকে 'হয়ে গেছে' চিহ্ন সরিয়ে দিলাম। |
| `voice/tools/actions.py:text#3` | Saved {name}. | {name} সেভ করে দিলাম। |
| `voice/tools/actions.py:text#4` | Removed {name} from saved places. | {name} সেভ করা জায়গা থেকে সরিয়ে দিলাম। |
| `voice/tools/actions.py:text#5` | Added ₹{amount:,} under {word}. | {word} খাতে ₹{amount:,} যোগ করে দিলাম। |
| `voice/tools/actions.py:text#6` | Here are options instead of {act.title}. Pick one. | {act.title}-এর বদলে কয়েকটা বিকল্প দেখাচ্ছি। পছন্দেরটা বেছে নিন। |
| `voice/tools/actions.py:where#1` | In your {trip_label(ctx)} trip,  | আপনার {trip_label(ctx)} ট্রিপে,  |
| `voice/tools/lookups.py:<inline>#1` | Did you mean {joined}? | আপনি কি {joined} বলছেন? |
| `voice/tools/lookups.py:<inline>#10` | You're at {name}. | আপনি {name}-এই আছেন। |
| `voice/tools/lookups.py:<inline>#11` | You're far from {name}: {km} km in a straight line. | আপনি {name} থেকে অনেক দূরে, সোজাসুজি {km} কিলোমিটার। |
| `voice/tools/lookups.py:<inline>#12` | For which day? | কোন দিনের জন্য? |
| `voice/tools/lookups.py:<inline>#13` | There's no forecast that far ahead yet. | এত দিন পরের আবহাওয়ার পূর্বাভাস এখনো নেই। |
| `voice/tools/lookups.py:<inline>#14` | I couldn't find that place. | জায়গাটা খুঁজে পেলাম না। |
| `voice/tools/lookups.py:<inline>#15` | Weather for which place? | কোন জায়গার আবহাওয়া? |
| `voice/tools/lookups.py:<inline>#16` | I couldn't get the weather right now. | এখন আবহাওয়ার খবর পাওয়া যাচ্ছে না। |
| `voice/tools/lookups.py:<inline>#17` | I couldn't get the weather right now. | এখন আবহাওয়ার খবর পাওয়া যাচ্ছে না। |
| `voice/tools/lookups.py:<inline>#18` | from {day} | {day} থেকে |
| `voice/tools/lookups.py:<inline>#19` | You don't have any trips yet. | আপনার এখনো কোনো ট্রিপ নেই। |
| `voice/tools/lookups.py:<inline>#2` | Which place? | কোন জায়গা? |
| `voice/tools/lookups.py:<inline>#3` | I couldn't find that place. | জায়গাটা খুঁজে পেলাম না। |
| `voice/tools/lookups.py:<inline>#4` | about {m} metres | প্রায় {m} মিটার |
| `voice/tools/lookups.py:<inline>#5` | about {txt} km | প্রায় {txt} কিলোমিটার |
| `voice/tools/lookups.py:<inline>#6` | What should I look for? A restaurant, cafe or hotel? | কী খুঁজব? রেস্টুরেন্ট, ক্যাফে নাকি হোটেল? |
| `voice/tools/lookups.py:<inline>#7` | Near which place should I look? | কোন জায়গার কাছে খুঁজব? |
| `voice/tools/lookups.py:<inline>#8` | Distance to which place? | কোন জায়গা পর্যন্ত দূরত্ব? |
| `voice/tools/lookups.py:<inline>#9` | I couldn't find that place. | জায়গাটা খুঁজে পেলাম না। |
| `voice/tools/lookups.py:DAY_ON` | On {day} {mon} | {day} {mon} |
| `voice/tools/lookups.py:MAPS_UNAVAILABLE` | Map search isn't available right now. | ম্যাপ সার্চ এখন পাওয়া যাচ্ছে না। |
| `voice/tools/lookups.py:MODE_WORDS[drive]` | by car | গাড়িতে |
| `voice/tools/lookups.py:MODE_WORDS[two_wheeler]` | by bike | বাইকে |
| `voice/tools/lookups.py:MODE_WORDS[walk]` | on foot | হেঁটে |
| `voice/tools/lookups.py:NEARBY_FOUND` | {Plural} {where}: {names}. Showing them on the map. | ?? {where} এই {Plural} পেলাম: {names}। ম্যাপে দেখাচ্ছি। |
| `voice/tools/lookups.py:NEARBY_NONE` | I couldn't find {plural} {where}. | ?? {where} কোনো {plural} পেলাম না। |
| `voice/tools/lookups.py:NO_LOCATION` | I couldn't get your location. Please turn location on. | আপনার লোকেশন পাওয়া গেল না। লোকেশন চালু করুন। |
| `voice/tools/lookups.py:NO_SUCH_TRIP` | I couldn't find a trip like that. | এমন কোনো ট্রিপ পেলাম না। |
| `voice/tools/lookups.py:RAIN_CHANCE` | {p}% chance of rain | বৃষ্টির সম্ভাবনা {p}% |
| `voice/tools/lookups.py:ROUTE_NONE_STRAIGHT` | {unavailable} In a straight line it's {straight}. | {unavailable} সোজাসুজি দূরত্ব {straight}। |
| `voice/tools/lookups.py:ROUTE_UNAVAILABLE` | Routes aren't available right now. | রুট এখন পাওয়া যাচ্ছে না। |
| `voice/tools/lookups.py:TEMP_HIGH` | high {t}°C | সর্বোচ্চ তাপমাত্রা {t}°C |
| `voice/tools/lookups.py:TRAVEL_REPLY` | {name} is {dist} from your location, {dur} {words}. | ?? {name} আপনার লোকেশন থেকে {dist}, {words} {dur} লাগবে। |
| `voice/tools/lookups.py:WEATHER_REPLY` | {when} in {name}: {parts}. | {when} {name}-এ {parts}। |
| `voice/tools/lookups.py:WHERE_HERE` | around you | আপনার আশেপাশে |
| `voice/tools/lookups.py:WHERE_NEAR` | near {spoken} | {spoken}-এর কাছে |
| `voice/tools/lookups.py:WHICH_MONTH` | the {mo} one | ?? {mo}-এর টা |
| `voice/tools/lookups.py:names[0]` | Today | আজ |
| `voice/tools/lookups.py:names[1]` | Tomorrow | কাল |
| `voice/tools/lookups.py:names[2]` | The day after tomorrow | পরশু |
| `voice/tools/lookups.py:reply#1` | Showing {label} on the map. | {label} ম্যাপে দেখাচ্ছি। |
| `voice/tools/lookups.py:reply#2` | {name} is in {where}. Shall I show it on the map? | {name} {where}-এ আছে। ম্যাপে দেখাব? |
| `voice/tools/lookups.py:reply#3` | I found {name}. Shall I show it on the map? | {name} পেয়েছি। ম্যাপে দেখাব? |
| `voice/tools/lookups.py:reply#4` | I couldn't find a route there. In a straight line it's {straight}. | ওখানে যাওয়ার রুট পেলাম না। সোজাসুজি দূরত্ব {straight}। |
| `voice/tools/lookups.py:reply#5` | You have no past trips. | আপনার কোনো পুরোনো ট্রিপ নেই। |
| `voice/tools/lookups.py:reply#6` | You don't have any trips yet. Want to plan one? | আপনার এখনো কোনো ট্রিপ নেই। নতুন ট্রিপ বানাবেন? |
| `voice/tools/lookups.py:reply#7` | Opened your {_short_name(t)} trip. | আপনার {_short_name(t)} ট্রিপ খুলে দিলাম। |
| `voice/tools/smart.py:ONE_STOP` | one stop | একটা জায়গা |
| `voice/tools/smart.py:TEXT[applied]` | Done. {what} | হয়ে গেছে। {what} |
| `voice/tools/smart.py:TEXT[budget_ask_amount]` | What should the budget be? | বাজেট কত রাখব? |
| `voice/tools/smart.py:TEXT[budget_change_q]` | Change the trip budget from {old} to {new}? | ট্রিপের বাজেট {old} থেকে {new} করে দেব? |
| `voice/tools/smart.py:TEXT[budget_high]` | The budget can be at most {max} rupees. How much is it? | বাজেট সর্বোচ্চ {max} টাকা হতে পারে, কত? |
| `voice/tools/smart.py:TEXT[budget_low]` | The budget must be at least {min} rupees. How much is it? | বাজেট অন্তত {min} টাকা হতে হবে, কত? |
| `voice/tools/smart.py:TEXT[budget_q]` | To save {saving}, shall I {what}? | ?? {saving} বাঁচাতে {what}? |
| `voice/tools/smart.py:TEXT[budget_same]` | The budget is already {amount}. | বাজেট আগে থেকেই {amount}। |
| `voice/tools/smart.py:TEXT[budget_set_done]` | Done. The budget is now {new}. | হয়ে গেছে, বাজেট এখন {new}। |
| `voice/tools/smart.py:TEXT[budget_set_q]` | Set the trip budget to {new}? | ট্রিপের বাজেট {new} রাখব? |
| `voice/tools/smart.py:TEXT[cancelled]` | Okay, nothing was changed. | ঠিক আছে, কিছু বদলানো হয়নি। |
| `voice/tools/smart.py:TEXT[day_applied]` | Day {n} is now: {titles}. | {n} নম্বর দিন এখন এরকম: {titles}। |
| `voice/tools/smart.py:TEXT[day_q_MINIMIZE_TRAVEL_TIME]` | Shall I reorder day {n} to cut travel time? | যাতায়াতের সময় কমাতে {n} নম্বর দিনের ক্রম বদলে দেব? |
| `voice/tools/smart.py:TEXT[day_q_MORE_SIGHTS]` | Shall I reorder day {n} to fit in more sights? | আরও বেশি জায়গা দেখার জন্য {n} নম্বর দিনের ক্রম বদলে দেব? |
| `voice/tools/smart.py:TEXT[day_q_RELAXED]` | Shall I make day {n} more relaxed? | ?? {n} নম্বর দিনটা একটু আরামের করে দেব? |
| `voice/tools/smart.py:TEXT[failed]` | I couldn't change the plan right now, please try again in a bit. | এখন প্ল্যান বদলাতে পারলাম না, একটু পরে আবার চেষ্টা করুন। |
| `voice/tools/smart.py:TEXT[forecast_unavailable]` | I couldn't get the weather right now. | এখন আবহাওয়ার খবর পাওয়া যাচ্ছে না। |
| `voice/tools/smart.py:TEXT[need_budget]` | First tell me your budget. How much is it? | আগে বাজেটটা বলুন, কত? |
| `voice/tools/smart.py:TEXT[need_day]` | Which day? Say the day number, or today or tomorrow. | কোন দিন? দিনের নম্বর বলুন, অথবা আজ বা কাল। |
| `voice/tools/smart.py:TEXT[no_activities]` | There are no activities on that day. | ওই দিনে কোনো অ্যাক্টিভিটি নেই। |
| `voice/tools/smart.py:TEXT[no_bad_weather_day]` | {when}, the weather looks fine, so there's no need to change the plan. | {when} আবহাওয়া ভালোই আছে, প্ল্যান বদলানোর দরকার নেই। |
| `voice/tools/smart.py:TEXT[no_bad_weather_trip]` | The weather looks fine for your trip, so there's no need to change the plan. | ট্রিপের সময় আবহাওয়া ভালোই আছে, প্ল্যান বদলানোর দরকার নেই। |
| `voice/tools/smart.py:TEXT[no_indoor_needed]` | The weather is bad, but none of your plans need changing. | আবহাওয়া খারাপ, তবে কোনো জায়গা বদলানোর দরকার নেই। |
| `voice/tools/smart.py:TEXT[no_itinerary]` | Your itinerary isn't ready yet. | আপনার ইটিনেরারি এখনো তৈরি হয়নি। |
| `voice/tools/smart.py:TEXT[no_savings]` | I couldn't find cheaper options. | এর চেয়ে সস্তা কোনো বিকল্প পেলাম না। |
| `voice/tools/smart.py:TEXT[no_trip]` | Open a trip first. | আগে একটা ট্রিপ খুলুন। |
| `voice/tools/smart.py:TEXT[not_found]` | I couldn't find that trip. | ট্রিপটা খুঁজে পেলাম না। |
| `voice/tools/smart.py:TEXT[outside_trip]` | The trip runs from {start} to {end}. Which day? | ট্রিপ {start} থেকে {end} পর্যন্ত। কোন দিন? |
| `voice/tools/smart.py:TEXT[past_day]` | That day has already passed. | ওই দিনটা পেরিয়ে গেছে। |
| `voice/tools/smart.py:TEXT[rate_limited]` | Please try again in a little while. | একটু পরে আবার চেষ্টা করুন। |
| `voice/tools/smart.py:TEXT[stale]` | The plan had already changed, so nothing was changed. | প্ল্যান আগেই বদলে গিয়েছিল, তাই কিছু বদলানো হয়নি। |
| `voice/tools/smart.py:TEXT[too_far]` | There's no forecast that far ahead yet. | এত দিন পরের আবহাওয়ার পূর্বাভাস এখনো নেই। |
| `voice/tools/smart.py:TEXT[weather_q]` | {when} the forecast is {cond}. Shall I {what}? | ?? {when} {cond} হওয়ার পূর্বাভাস আছে। {what}? |
| `voice/tools/smart.py:TEXT[within_budget]` | Your plan is already within budget. | আপনার প্ল্যান আগে থেকেই বাজেটের মধ্যে আছে। |

## Composed in code (not a single table entry)

| where | English | Bengali |
|---|---|---|
| `voice/agent.py:FALLBACK_REPLY_BN` | Sorry, I didn't get that. Please say it again. | দুঃখিত, বুঝতে পারলাম না। আবার বলুন। |
| `voice/pipeline.py:EMPTY_TRANSCRIPT_REPLY_BN` | I didn't hear anything. Please say it again. | কিছু শুনতে পেলাম না, আবার বলুন। |
| `voice/draft.py:nights_words` | 2 nights | 2 রাত |
| `voice/draft.py:people_words` | 2 adults, 1 child | 2 জন প্রাপ্তবয়স্ক, 1 জন বাচ্চা |
| `voice/draft.py:say_date` | 25 December | 25 ডিসেম্বর (months: জানুয়ারি ... ডিসেম্বর) |
| `voice/tools/lookups.py:spoken_duration` | 1 hour 5 minutes | 1 ঘণ্টা 5 মিনিট |
| `voice/tools/lookups.py:list_my_trips` | You have 3 trips: ... and more. | আপনার 3টি ট্রিপ আছে: ..., আরও আছে। |
| `voice/tools/lookups.py:which_trip_question` | You have 2 Goa trips: ... or ...? | Goa-এর 2টি ট্রিপ আছে: ... নাকি ...? |
| `voice/tools/smart.py:summarize_replacements` | replace A with B, and 2 more | ?? A-এর জায়গায় B রাখব, আর 2টা |
| `voice/tools/smart.py:ONE_STOP` | one stop | একটা জায়গা |
| `voice/tools/actions.py:DAY_TAG / ASK_WHICH` | Which one: X (day 1) or Y (day 2)? | কোনটা: X (1 নম্বর দিন) নাকি Y (2 নম্বর দিন)? |
| `voice/languages.py:OR_WORD / AND_WORD` | or / and | নাকি / আর |
| `booking_flow.py:_person_label` | Traveller 1 / Child 1 | যাত্রী 1 / বাচ্চা 1 |
| `booking_flow.py:spoken_review` | Cheapest flight | ?? সবচেয়ে সস্তা flight |
| `voice/stt.py:LANGUAGE_PROMPTS[bn]` (speech-to-text spelling hint, not spoken) | - | নমস্কার। আমি কলকাতা থেকে দার্জিলিং যেতে চাই, 3 দিনের জন্য, বাজেট 20 হাজার। ইটিনেরারি দেখান। |
| `voice/languages.py` model line (not spoken) | - | Always reply in Bengali, whatever language the user speaks; use Bangla script. |

## Listening words added (please check spellings and add common ones)

- **Yes** (`voice/confirm_words.py`, `voice/agent.py`, `voice/booking_voice.py`): হ্যাঁ, হ্যা, হাঁ, হুঁ, ঠিক, ঠিক আছে, সঠিক, অবশ্যই, নিশ্চয়ই, ওকে, ইয়েস, কনফার্ম, একদম, চলবে, করে দিন, করে দাও, বানিয়ে দিন, বানিয়ে দাও, শুরু করুন, এগিয়ে যান, দেখাও, দেখান
- **No** : না, নাহ, নয়, নো, ভুল, দরকার নেই, থাক, থাকুক, বাতিল, ক্যানসেল, দাঁড়ান, দাঁড়াও, থামুন, থামো, বদলান, বদলাও, পাল্টান
- **Cancel** (trip draft, booking): বাতিল, ক্যানসেল, থাক, এখন না, বাদ দিন, বাদ দাও, বুকিং বাতিল, বন্ধ করুন, বন্ধ করো
- **Thanks / acknowledgement**: ধন্যবাদ, থ্যাংক, থ্যাংকস, থ্যাঙ্কস, আচ্ছা, বাহ, দারুণ, খুব ভালো, বেশ
- **Don't know / skip** (starting city, purpose): জানি না, জানিনা, জানা নেই, বলতে পারব না, কিছু না, কিছুই না, বাদ দিন, পরে, স্কিপ, এখন না
- **You decide** (booking): যেকোনো, আপনি ঠিক করুন, আপনিই ঠিক করুন, আপনি দেখুন, আপনি দেখে নিন, যা হোক, যেটা ভালো, আপনার পছন্দ
- **Numbers 0-100** (`voice/bn_words.py`): শূন্য, এক, দুই, তিন ... একশো, plus দু, দুটো, দুটি, একটা, একটি, তিনটে, চারটে, পাঁচটা, ছ, চৌদ্দ, বিশ, ত্রিশ, উনত্রিশ, একশ, একশত; zero answers: কেউ না, কেউ নেই, নেই, কোনো বাচ্চা নেই
- **Money**: হাজার, লাখ, লক্ষ, কোটি, টাকা
- **Months**: জানুয়ারি, ফেব্রুয়ারি, মার্চ, এপ্রিল, মে, জুন, জুলাই, আগস্ট, সেপ্টেম্বর, অক্টোবর, নভেম্বর, ডিসেম্বর (also জানুয়ারী, ফেব্রুয়ারী, আগষ্ট)
- **Days**: আজ, আজকে, কাল, কালকে, আগামীকাল, পরশু, পরশুদিন
- **Purposes** (`trip_purpose.py`): বেড়ানো, বেড়াতে, ঘুরতে, ছুটি, হলিডে, ভেকেশন (holiday); কাজ, কাজে, অফিস, মিটিং, ক্লায়েন্ট, বিজনেস, ব্যবসা (work); হ্যাকাথন, ইভেন্ট, কনফারেন্স, সেমিনার, বিয়ে, ওয়ার্কশপ, ইন্টারভিউ, পরীক্ষা (event); তীর্থ, তীর্থযাত্রা, দর্শন, পুজো, পূজা (pilgrimage); with common -এ / -ের forms
- **Booking**: বুক, বুকিং; ফ্লাইট, প্লেন, বিমান, ট্রেন, রেল, হোটেল; সকাল, ভোর, দুপুর, বিকেল, সন্ধ্যা, রাত (+ -এ forms); স্লিপার, এসি, ফার্স্ট / সেকেন্ড / থার্ড, প্রথম / দ্বিতীয় / তৃতীয়; বাজেট, সস্তা, স্টার, লাক্সারি; রুম, ঘর; তৎকাল; বছর, বয়স (age); নাম, আমার নাম; যাত্রী; airlines: ইন্ডিগো, এয়ার ইন্ডিয়া, এয়ার ইন্ডিয়া এক্সপ্রেস, স্পাইসজেট, আকাসা, অ্যালায়েন্স এয়ার, স্টার এয়ার, ফ্লাই 91
- **Trip delete** (refused by code): মুছে, মুছুন, মোছো, ডিলিট, সরাও, সরান + ট্রিপ / প্ল্যান / ইটিনেরারি
- **Starting city words**: কোথা, কোথায়, কোথাকার, শুরু; when-words কবে, তারিখ
