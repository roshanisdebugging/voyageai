# Voice Testing — testing.md

> **Test-only saving for Step 1 of `voicefirst.md`.**
> Step 1 builds the real voice pipeline (`/ws/voice`, `backend/voice/`, `src/voice/`). This file adds **one optional stage** to it: saving each recording and its transcript on the developer's machine.
> Saving uses **local Postgres only**, never the cloud database, and is **off by default** (`VOICE_DEBUG_STORE=false`). With it off, Step 1 stores nothing, as `voicefirst.md` says.

## Goal

Keep real recordings and their transcripts, with timings, so Groq Whisper can be judged on Hindi, English and Hinglish, and later compared with other providers.

## Where it plugs in

Nothing new on the frontend. On the backend there is one extra file:

| File | Job |
| --- | --- |
| `backend/voice/debug_store.py` | Runs only when `VOICE_DEBUG_STORE=true` **and** `VOICE_DEBUG_DATABASE_URL` is set. Saves the WAV to `test_audio_folder/`, writes rows to the two tables below, and merges a session's audio at the end. |

`backend/voice/pipeline.py` calls it as the last stage of a turn, after STT. If saving fails, the transcript is still sent to the app and the failure is logged.

## What gets saved

1. **Each recording:**
   - The WAV is saved as `test_audio_folder/<session_id>/<speech_id>.wav`.
   - One row is written in `voice_speeches`.
2. **End of session** (the app sends `{"type":"end_session"}` or the socket closes):
   - That session's WAVs are joined in order, with 0.5 s of silence between them, into `test_audio_folder/<session_id>/session_full.wav`.
   - One row in `voice_sessions` is filled in.

The IDs are real ones:
- `user_id` and `session_id` come from the login token (the real `sessions` table).
- `speech_id` is the `turn_id` the pipeline already creates for each recording.

## Local database: two tables

The connection is `VOICE_DEBUG_DATABASE_URL`, pointing at **local Postgres** (e.g. `postgresql://postgres:postgres@localhost:5432/voice_test`). It's kept separate from `DATABASE_URL`, so these tables can never end up in the cloud database. The tables are created on startup if they don't exist.

### `voice_speeches`: one row per recording

| Column | Type | Notes |
| --- | --- | --- |
| `speech_id` | text PK | Same as the pipeline's `turn_id` |
| `session_id` | text | Real `sessions.id` |
| `user_id` | text | Real user |
| `conversation_id` | text | From the app's `start` message |
| `turn_index` | int | 1, 2, 3… within the session |
| `audio_path` | text | `test_audio_folder/<session_id>/<speech_id>.wav` |
| `audio_duration_ms` | int | Length of the recording |
| `transcription` | text | What Groq returned |
| `language` | text | Language Groq detected |
| `stt_provider` / `stt_model` | text | e.g. `groq` / `whisper-large-v3-turbo` |
| `stt_time_ms` | int | **Time taken to get Groq's response** (request sent → response received) |
| `total_time_ms` | int | `stop` received → transcript sent to the app |
| `status` | text | `ok` or `failed` |
| `error` | text | Error message if failed |
| `created_at` | timestamptz | |

### `voice_sessions`: one row per session

| Column | Type | Notes |
| --- | --- | --- |
| `session_id` | text PK | Real `sessions.id` |
| `user_id` | text | |
| `started_at` | timestamptz | First recording |
| `ended_at` | timestamptz | `end_session` or socket close |
| `speech_count` | int | Number of recordings |
| `merged_audio_path` | text | `test_audio_folder/<session_id>/session_full.wav` |
| `total_audio_ms` | int | Total length of all recordings |
| `avg_stt_time_ms` | int | Average Groq response time for the session |

## Settings (`backend/.env`, local machine only)

```
VOICE_DEBUG_STORE=true
VOICE_DEBUG_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/voice_test
VOICE_DEBUG_AUDIO_DIR=test_audio_folder
```

Add `test_audio_folder/` to `.gitignore`. Never set these on the cloud server.

## Done when

- [x] With `VOICE_DEBUG_STORE=true`, every recording creates a WAV in `test_audio_folder/<session_id>/` and a row in `voice_speeches` with the transcript, `stt_time_ms` and `total_time_ms`
- [x] Ending a session creates `session_full.wav` with all recordings in order and fills `voice_sessions`
- [x] A failed Groq call still saves the WAV and a `failed` row
- [x] With `VOICE_DEBUG_STORE=false`, or no `VOICE_DEBUG_DATABASE_URL`, nothing is saved and transcripts still show in the app
- [ ] About 20 Hinglish recordings saved, for an accuracy and timing review *(owner, by speaking into the app)*

**Status (13 Nov 2026):** built and tested; see "Step 1 notes" in `voicefirst.md`.
- The local DB `voice_test` exists on the developer machine (Postgres 17, user `postgres`). The connection string, with its password, is only in `backend/.env`, which git ignores.
- The tables are created when the backend starts.
- `debug_store` refuses any `VOICE_DEBUG_DATABASE_URL` whose host isn't `localhost`/`127.0.0.1`.
- `test_audio_folder/` is in `.gitignore`.

## Useful queries

```sql
-- slowest Groq responses
SELECT speech_id, audio_duration_ms, stt_time_ms, transcription
FROM voice_speeches ORDER BY stt_time_ms DESC LIMIT 10;

-- average timing per session
SELECT session_id, speech_count, avg_stt_time_ms FROM voice_sessions ORDER BY started_at DESC;
```

## After testing

Set `VOICE_DEBUG_STORE=false`. Delete `test_audio_folder/` and the local `voice_test` database when they're no longer needed.