"""
Voice pipeline (voicefirst.md, step 1).

/ws/voice: the app streams 16 kHz mono PCM, the backend transcribes it with Groq Whisper
and sends the transcript back. Audio and words are not stored, except by the test-only
debug store (testing.md), which is off unless VOICE_DEBUG_STORE=true.
"""
