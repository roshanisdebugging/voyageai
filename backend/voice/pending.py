"""
Pending confirmations and the Confirm card (voicefirst.md "Step 4 in detail").

One pending confirmation per user + conversation: Redis voice:confirm:{user}:{conversation}, 5 minutes.
(Separate from voice:pending:*, which holds step 3's "where is X -> map par dikhaun?" map actions.)
Saving a new one replaces the old one. confirm() takes it ONCE: a second confirm finds nothing.
Everything is keyed by the session's user, so another user's pending ID is simply not found.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Optional

PENDING_TTL_SECONDS = 5 * 60


def _key(user_id: str, conversation_id: str) -> str:
    return f"voice:confirm:{user_id}:{conversation_id}"


def get(redis_conn, user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
    try:
        raw = redis_conn.get(_key(user_id, conversation_id))
        return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw) if raw else None
    except Exception:
        return None


def save(redis_conn, user_id: str, conversation_id: str, tool: str, summary: str,
         data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Saves (and replaces) the conversation's pending confirmation. Returns {id, tool, summary, ...}."""
    pending = {"id": f"pc_{uuid.uuid4().hex[:16]}", "tool": tool, "summary": summary, "data": data or {}, "created": time.time()}
    redis_conn.setex(_key(user_id, conversation_id), PENDING_TTL_SECONDS, json.dumps(pending))
    return pending


def take(redis_conn, user_id: str, conversation_id: str, pending_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Removes and returns the pending confirmation (only if pending_id matches, when given). Atomic: one taker."""
    key = _key(user_id, conversation_id)
    try:
        raw = redis_conn.get(key)
        if not raw:
            return None
        pending = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        if pending_id is not None and pending.get("id") != pending_id:
            return None
        if not redis_conn.delete(key):   # someone else took it between get and delete
            return None
        return pending
    except Exception:
        return None


def clear(redis_conn, user_id: str, conversation_id: str) -> None:
    try:
        redis_conn.delete(_key(user_id, conversation_id))
    except Exception:
        pass
