"""
TEST ONLY (testing.md): saves each recording and its transcript on the developer's machine.

Runs only when VOICE_DEBUG_STORE=true AND VOICE_DEBUG_DATABASE_URL is set. That URL must point
at LOCAL Postgres; it is deliberately separate from DATABASE_URL so these tables can never land
in the cloud database. Never set these variables on the cloud server.

  VOICE_DEBUG_STORE=true
  VOICE_DEBUG_DATABASE_URL=postgresql://postgres:<password>@localhost:5432/voice_test
  VOICE_DEBUG_AUDIO_DIR=test_audio_folder        (relative to backend/)

Files: <audio dir>/<session_id>/<speech_id>.wav, and session_full.wav when a session ends.
"""
import logging
import os
import threading
import wave
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (Column, DateTime, Integer, MetaData, String, Table, Text, create_engine,
                        func, select, text)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

from voice.messages import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH
from voice.stt import DEFAULT_STT_MODEL, pcm_to_wav

if TYPE_CHECKING:  # avoid an import cycle with pipeline.py
    from voice.pipeline import TurnContext, TurnResult

logger = logging.getLogger("voice")

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SILENCE_BETWEEN_MS = 500
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")

# Own MetaData, never the app's Base: these tables must not be created in DATABASE_URL.
metadata = MetaData()

voice_speeches = Table(
    "voice_speeches", metadata,
    Column("speech_id", Text, primary_key=True),
    Column("session_id", Text, nullable=False, index=True),
    Column("user_id", Text, nullable=False),
    Column("conversation_id", Text),
    Column("turn_index", Integer, nullable=False),
    Column("audio_path", Text),
    Column("audio_duration_ms", Integer),
    Column("transcription", Text),
    Column("language", Text),
    Column("stt_provider", Text),
    Column("stt_model", Text),
    Column("stt_time_ms", Integer),
    Column("total_time_ms", Integer),
    Column("reply_text", Text),          # step 1b; the reply AUDIO is never saved
    Column("tts_time_ms", Integer),
    Column("status", String(16), nullable=False),
    Column("error", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

voice_sessions = Table(
    "voice_sessions", metadata,
    Column("session_id", Text, primary_key=True),
    Column("user_id", Text, nullable=False),
    Column("started_at", DateTime(timezone=True)),
    Column("ended_at", DateTime(timezone=True)),
    Column("speech_count", Integer),
    Column("merged_audio_path", Text),
    Column("total_audio_ms", Integer),
    Column("avg_stt_time_ms", Integer),
)

_engine: Optional[Engine] = None
_engine_lock = threading.Lock()
_session_locks: dict = {}


def _db_url() -> str:
    return (os.getenv("VOICE_DEBUG_DATABASE_URL") or "").strip()


def enabled() -> bool:
    return (os.getenv("VOICE_DEBUG_STORE") or "").strip().lower() == "true" and bool(_db_url())


def audio_root() -> str:
    raw = (os.getenv("VOICE_DEBUG_AUDIO_DIR") or "test_audio_folder").strip()
    return raw if os.path.isabs(raw) else os.path.join(BACKEND_DIR, raw)


def _rel(path: str) -> str:
    """Path as stored in the DB: relative to backend/ when possible, with forward slashes."""
    try:
        return os.path.relpath(path, BACKEND_DIR).replace(os.sep, "/")
    except ValueError:  # different drive on Windows
        return path.replace(os.sep, "/")


def _engine_or_create() -> Engine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                url = _db_url()
                engine = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2)
                host = (engine.url.host or "").lower()
                if host not in LOCAL_HOSTS:
                    engine.dispose()
                    raise RuntimeError("VOICE_DEBUG_DATABASE_URL must point at a local database")
                metadata.create_all(engine)
                # create_all() never adds columns to an existing table: add the step 1b ones.
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE voice_speeches ADD COLUMN IF NOT EXISTS reply_text TEXT"))
                    conn.execute(text("ALTER TABLE voice_speeches ADD COLUMN IF NOT EXISTS tts_time_ms INTEGER"))
                _engine = engine
    return _engine


def init() -> bool:
    """Creates the tables at startup when enabled. Returns True if the store is ready."""
    if not enabled():
        return False
    try:
        _engine_or_create()
        logger.warning("[VOICE DEBUG STORE] ON: saving recordings to %s and local DB '%s'",
                       _rel(audio_root()), _engine.url.database if _engine else "?")
        return True
    except Exception as err:
        logger.warning("[VOICE DEBUG STORE] could not start (%s); nothing will be saved", type(err).__name__)
        return False


def _session_lock(session_id: str) -> threading.Lock:
    with _engine_lock:
        return _session_locks.setdefault(session_id, threading.Lock())


def _safe_dir_name(value: str) -> str:
    return "".join(ch for ch in value if ch.isalnum() or ch in "-_") or "unknown"


def save_speech(pcm: bytes, ctx: "TurnContext", result: "TurnResult", total_ms: int) -> None:
    """Saves the WAV (also for failed turns) and one voice_speeches row."""
    engine = _engine_or_create()
    session_dir = os.path.join(audio_root(), _safe_dir_name(ctx.session_id))
    os.makedirs(session_dir, exist_ok=True)
    wav_path = os.path.join(session_dir, f"{_safe_dir_name(ctx.turn_id)}.wav")
    with open(wav_path, "wb") as f:
        f.write(pcm_to_wav(pcm))

    with _session_lock(ctx.session_id), engine.begin() as conn:
        count = conn.execute(
            select(func.count()).select_from(voice_speeches).where(voice_speeches.c.session_id == ctx.session_id)
        ).scalar_one()
        conn.execute(voice_speeches.insert().values(
            speech_id=ctx.turn_id,
            session_id=ctx.session_id,
            user_id=ctx.user_id,
            conversation_id=ctx.conversation_id,
            turn_index=count + 1,
            audio_path=_rel(wav_path),
            audio_duration_ms=result.duration_ms,
            transcription=result.text if result.ok else None,
            language=result.language,
            stt_provider=result.stt_provider or (os.getenv("VOICE_STT_PROVIDER") or "groq"),
            stt_model=result.stt_model or os.getenv("VOICE_STT_MODEL") or DEFAULT_STT_MODEL,
            stt_time_ms=result.stt_ms if result.ok else None,
            total_time_ms=total_ms,
            reply_text=result.reply_text,
            tts_time_ms=result.tts_ms if result.reply_text is not None else None,
            status="ok" if result.ok else "failed",
            error=None if result.ok else f"{result.error_code}: {result.error_detail}",
            created_at=ctx.started_at,
        ))


def end_session(user_id: str, session_id: str) -> Optional[str]:
    """Joins the session's WAVs in order (0.5 s silence between) and upserts voice_sessions."""
    engine = _engine_or_create()
    with _session_lock(session_id):
        with engine.connect() as conn:
            rows = conn.execute(
                select(voice_speeches.c.audio_path, voice_speeches.c.audio_duration_ms,
                       voice_speeches.c.stt_time_ms, voice_speeches.c.created_at)
                .where(voice_speeches.c.session_id == session_id)
                .order_by(voice_speeches.c.turn_index)
            ).all()
        if not rows:
            return None

        session_dir = os.path.join(audio_root(), _safe_dir_name(session_id))
        merged_path = os.path.join(session_dir, "session_full.wav")
        silence = b"\x00" * (SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS * SILENCE_BETWEEN_MS // 1000)
        os.makedirs(session_dir, exist_ok=True)
        with wave.open(merged_path, "wb") as out:
            out.setnchannels(CHANNELS)
            out.setsampwidth(SAMPLE_WIDTH)
            out.setframerate(SAMPLE_RATE)
            first = True
            for row in rows:
                path = row.audio_path if os.path.isabs(row.audio_path) else os.path.join(BACKEND_DIR, row.audio_path)
                if not os.path.exists(path):
                    continue
                with wave.open(path, "rb") as w:
                    frames = w.readframes(w.getnframes())
                if not first:
                    out.writeframes(silence)
                out.writeframes(frames)
                first = False

        stt_times = [r.stt_time_ms for r in rows if r.stt_time_ms is not None]
        values = dict(
            user_id=user_id,
            started_at=min(r.created_at for r in rows),
            ended_at=datetime.now(timezone.utc),
            speech_count=len(rows),
            merged_audio_path=_rel(merged_path),
            total_audio_ms=sum(r.audio_duration_ms or 0 for r in rows),
            avg_stt_time_ms=int(sum(stt_times) / len(stt_times)) if stt_times else None,
        )
        with engine.begin() as conn:
            stmt = pg_insert(voice_sessions).values(session_id=session_id, **values)
            conn.execute(stmt.on_conflict_do_update(index_elements=[voice_sessions.c.session_id], set_=values))
        return merged_path
