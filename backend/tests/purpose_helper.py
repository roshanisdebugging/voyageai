"""
Test helper (not a test): the voice flows written before feat/trip-purpose don't test the purpose question, which now
comes after the origin question on its own turn ("Kis kaam se ja rahe hain? ..."). past_purpose() answers it
"pata nahi" (handled by code, no model call) and returns the next reply, with the words said before the question
kept in front, exactly as the flow said them before the purpose question existed. It also fails if the question
is asked a second time for the same draft (a new draft in the same conversation may ask it again).
The purpose flow itself is tested in tests/test_trip_purpose.py.
"""
from voice import draft as D

PURPOSE_QUESTIONS = tuple(D.QUESTIONS["purpose"][lang] for lang in ("hi", "en"))


def past_purpose(result, conversation_id, load_draft, say, check=None):
    """result: the turn's AgentResult; load_draft(): the conversation's draft; say(text): one more voice turn.
    Returns result unchanged unless it asked ONLY the purpose question."""
    q = next((q for q in PURPOSE_QUESTIONS if (result.reply_text or "").endswith(q)), None)
    if q is None or result.step != "ask":
        return result
    d = load_draft()
    if d is None or d.last_asked != ["purpose"]:
        return result
    if check is not None:
        check(f"purpose question asked once for this draft ({conversation_id})", d.purpose_asked == 1, d.purpose_asked)
    elif d.purpose_asked != 1:
        raise AssertionError(f"purpose question asked {d.purpose_asked} times for one draft in {conversation_id}")
    prefix = result.reply_text[: -len(q)].strip()
    nxt = say("I don't know" if q == D.QUESTIONS["purpose"]["en"] else "pata nahi")
    dest = (d.destination or {}).get("name") or ""
    # The product rule from before: "<destination>." is not said before "<origin> se <destination>, ..." (the read-back
    # already names it).
    if nxt.step == "confirm_date" and d.origin_city and dest and prefix.startswith(dest):
        prefix = prefix[len(dest):].lstrip(" .,").strip()
        prefix = "" if prefix.endswith(("din.", "days.")) and len(prefix.split()) <= 3 else prefix
    nxt.reply_text = f"{prefix} {nxt.reply_text}".strip()
    return nxt
