"""
/ws/voice: the voice pipeline's own WebSocket (voicefirst.md, step 1).

Login: the `voyageai_session` cookie, or, when the browser doesn't send it, a first text
message {"type":"auth","token":"..."} within 5 seconds. Tokens are never read from the URL.
A browser Origin that isn't in ALLOWED_ORIGINS is refused, so another site can't ride the cookie.

Per connection: one recording at a time, 30 s / 960 KB per recording (cut, then transcribed).
Per user: 15 recordings a minute and 100 a day (Redis, fails closed).
Transcription runs in a threadpool, so /ws/app traffic is never blocked by a voice turn.
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from voice import debug_store, messages as m, pipeline

logger = logging.getLogger("voice")

COOKIE_NAME = "voyageai_session"
AUTH_TIMEOUT_SECONDS = 5
RATE_PER_MINUTE = 15
RATE_PER_DAY = 100

CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN_ORIGIN = 4403


@dataclass
class _Conn:
    user_id: str
    session_id: str
    token: str
    recording: bool = False
    processing: bool = False
    auto_stopped: bool = False       # last recording was cut at 30 s; the app's late "stop" is expected
    buffer: bytearray = field(default_factory=bytearray)
    ctx: Optional[pipeline.TurnContext] = None
    turns: int = 0
    task: Optional[asyncio.Task] = None


def _resolve_session(token: str) -> Optional[Tuple[str, str]]:
    """(user_id, sessions.id) for a valid, unexpired, unrevoked login token; else None."""
    if not token:
        return None
    import auth
    import database
    from models_db import SessionModel
    try:
        with database.SessionLocal() as db:
            user, _profile, _prefs = auth.get_session_user(db, token)
            record = db.query(SessionModel).filter(SessionModel.token_hash == auth.hash_token(token)).first()
            if not record:
                return None
            return user.id, record.id
    except Exception:
        return None


async def _send(ws: WebSocket, payload: dict) -> bool:
    try:
        await ws.send_text(json.dumps(payload))
        return True
    except Exception:
        return False


async def _check_rate_limits(user_id: str) -> Optional[str]:
    """None if allowed, else an error code."""
    from rate_limiter import check_ws_rate_limit
    try:
        await check_ws_rate_limit("voice", user_id, RATE_PER_MINUTE, 60)
        await check_ws_rate_limit("voice_day", user_id, RATE_PER_DAY, 86_400)
        return None
    except HTTPException as err:
        return m.ErrorCode.RATE_LIMITED if err.status_code == 429 else m.ErrorCode.UNAVAILABLE
    except Exception:
        return m.ErrorCode.UNAVAILABLE


async def _process_turn(ws: WebSocket, conn: _Conn, pcm: bytes, ctx: pipeline.TurnContext, stop_at: float) -> None:
    result: Optional[pipeline.TurnResult] = None
    total_ms = 0
    try:
        result = await run_in_threadpool(pipeline.run_turn, pcm, ctx)
        if result.ok:
            payload = m.transcript(ctx.turn_id, result.text, result.language, result.duration_ms,
                                   result.stt_ms, truncated=ctx.truncated)
        else:
            payload = m.error(result.error_code or m.ErrorCode.STT_FAILED, turn_id=ctx.turn_id)
        await _send(ws, payload)
        total_ms = int((time.perf_counter() - stop_at) * 1000)  # stop -> transcript sent

        # Step 1b: the spoken reply follows the transcript. A TTS failure never breaks the turn.
        if result.ok:
            await run_in_threadpool(pipeline.make_reply, ctx, result)
            await _send(ws, m.reply(ctx.turn_id, result.reply_text or "", result.reply_audio_b64,
                                    result.reply_mime, result.tts_ms))
            if result.tts_error and result.tts_error != "tts_disabled":
                await _send(ws, m.error(m.ErrorCode.TTS_FAILED, turn_id=ctx.turn_id))
    except Exception as err:
        logger.warning("[VOICE] turn=%s crashed: %s", ctx.turn_id, type(err).__name__)
        await _send(ws, m.error(m.ErrorCode.STT_FAILED, turn_id=ctx.turn_id))
    finally:
        conn.processing = False
    # Last stage (test-only saving). The app already has its answer.
    if result is not None:
        await run_in_threadpool(pipeline.after_turn, pcm, ctx, result, total_ms)


def _finish_recording(ws: WebSocket, conn: _Conn) -> Optional[str]:
    """Ends the current recording and starts transcription. Returns an error code if it can't."""
    conn.recording = False
    pcm = bytes(conn.buffer[: len(conn.buffer) // 2 * 2])  # whole 16-bit samples only
    conn.buffer = bytearray()
    ctx = conn.ctx
    conn.ctx = None
    if ctx is None:
        return m.ErrorCode.NOT_RECORDING
    if len(pcm) < m.MIN_BYTES:
        return m.ErrorCode.TOO_SHORT
    conn.processing = True
    conn.turns += 1
    conn.task = asyncio.create_task(_process_turn(ws, conn, pcm, ctx, time.perf_counter()))
    return None


async def _handle_text(ws: WebSocket, conn: _Conn, raw: str) -> bool:
    """Returns False when the socket should close."""
    try:
        msg = json.loads(raw)
        kind = msg.get("type") if isinstance(msg, dict) else None
    except ValueError:
        kind, msg = None, {}

    if kind == "auth":
        return True  # already logged in via cookie; harmless repeat

    if kind == "start":
        if conn.recording or conn.processing:
            await _send(ws, m.error(m.ErrorCode.BUSY))
            return True
        identity = await run_in_threadpool(_resolve_session, conn.token)
        if not identity or identity[0] != conn.user_id:
            await _send(ws, m.error(m.ErrorCode.UNAUTHORIZED))
            return False
        limited = await _check_rate_limits(conn.user_id)
        if limited:
            await _send(ws, m.error(limited))
            return True
        conn.ctx = pipeline.TurnContext(
            turn_id=pipeline.new_turn_id(), user_id=conn.user_id, session_id=conn.session_id,
            conversation_id=str(msg.get("conversation_id") or "")[:100] or None,
            screen=str(msg.get("screen") or "")[:200] or None,
        )
        conn.recording = True
        conn.auto_stopped = False
        conn.buffer = bytearray()
        await _send(ws, m.recording(conn.ctx.turn_id))
        return True

    if kind == "stop":
        if not conn.recording:
            if conn.auto_stopped:          # already cut at 30 s and being transcribed
                conn.auto_stopped = False
                return True
            await _send(ws, m.error(m.ErrorCode.NOT_RECORDING))
            return True
        turn_id = conn.ctx.turn_id if conn.ctx else None
        err = _finish_recording(ws, conn)
        if err:
            await _send(ws, m.error(err, turn_id=turn_id))
        return True

    if kind == "end_session":
        await run_in_threadpool(pipeline.end_session, conn.user_id, conn.session_id)
        return True

    await _send(ws, m.error(m.ErrorCode.BAD_MESSAGE))
    return True


async def _handle_audio(ws: WebSocket, conn: _Conn, data: bytes) -> None:
    if not conn.recording:
        return  # late chunks after a stop or after the 30 s cut
    room = m.MAX_BYTES - len(conn.buffer)
    conn.buffer.extend(data[:room])
    if len(conn.buffer) >= m.MAX_BYTES and conn.ctx:
        conn.ctx.truncated = True
        conn.auto_stopped = True
        turn_id = conn.ctx.turn_id
        err = _finish_recording(ws, conn)
        if err:
            await _send(ws, m.error(err, turn_id=turn_id))


async def _authenticate(ws: WebSocket) -> Optional[_Conn]:
    token = ws.cookies.get(COOKIE_NAME)
    identity = await run_in_threadpool(_resolve_session, token) if token else None
    if not identity:
        try:
            first = await asyncio.wait_for(ws.receive(), AUTH_TIMEOUT_SECONDS)
            msg = json.loads(first.get("text") or "{}")
            if isinstance(msg, dict) and msg.get("type") == "auth":
                token = str(msg.get("token") or "")
                identity = await run_in_threadpool(_resolve_session, token)
        except (asyncio.TimeoutError, ValueError, KeyError, RuntimeError, WebSocketDisconnect):
            identity = None
    if not identity:
        return None
    return _Conn(user_id=identity[0], session_id=identity[1], token=token)


def mount_voice(app: FastAPI, origin_allowed: Callable[[Optional[str]], bool]) -> None:
    """Registers /ws/voice and starts the test-only debug store if it's switched on."""
    if not logger.handlers:  # uvicorn doesn't configure app loggers; voice logs carry no words
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    debug_store.init()

    @app.websocket("/ws/voice")
    async def voice_socket(websocket: WebSocket):
        origin = websocket.headers.get("origin")
        if origin and not origin_allowed(origin):
            await websocket.close(code=CLOSE_FORBIDDEN_ORIGIN)
            return
        await websocket.accept()

        conn = await _authenticate(websocket)
        if not conn:
            await _send(websocket, m.error(m.ErrorCode.UNAUTHORIZED))
            await websocket.close(code=CLOSE_UNAUTHORIZED)
            return
        await _send(websocket, m.ready())

        try:
            while True:
                frame = await websocket.receive()
                if frame.get("type") == "websocket.disconnect":
                    break
                if frame.get("bytes") is not None:
                    await _handle_audio(websocket, conn, frame["bytes"])
                elif frame.get("text") is not None:
                    if not await _handle_text(websocket, conn, frame["text"]):
                        await websocket.close(code=CLOSE_UNAUTHORIZED)
                        break
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            conn.buffer = bytearray()  # a recording cut off by a disconnect is dropped
            if conn.task and not conn.task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(conn.task), 25)
                except Exception:
                    pass
            if conn.turns:
                await run_in_threadpool(pipeline.end_session, conn.user_id, conn.session_id)
