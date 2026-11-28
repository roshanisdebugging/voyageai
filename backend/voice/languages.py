"""
The voice languages the user can choose (feat/language). ONE table: adding a language is one entry here.

The user's choice ("voice language") comes with every voice turn ("start" message, field "language") and with the
Confirm / Cancel taps. It is one of:
  "auto"  the default: exactly the behaviour from before. STT detects the language, voice/lang.detect_lang picks
          the Hinglish ("hi") or English ("en") templates from the user's words, the model replies in the language
          the user spoke, and the TTS voice follows the reply's own words.
  a code  from LANGUAGES with selectable=True: STT is pinned to stt_code, every code-written reply uses that
          language's templates, the model is told "Always reply in <prompt_name>, whatever language the user
          speaks", and TTS uses tts_code.
Anything else (unknown, empty, not a string, not selectable) means "auto".

Templates exist only for "hi" (Hinglish in Roman script, as the existing templates are) and "en". A language with
has_templates=False gets the English templates (template_lang) and one log line per conversation:
"[LANG] templates=fallback_en lang=<code>". Its STT, TTS and model reply language still follow the table.

A new language, e.g. Bengali, is one entry (selectable only once someone has listened to it):
    "bn": Language("bn", "Bengali", "বাংলা", stt_code="bn", tts_code="bn-IN", prompt_name="Bengali",
                   has_templates=False, selectable=True),
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional

AUTO = "auto"


@dataclass(frozen=True)
class Language:
    code: str              # our code; also the key of the templates when has_templates
    name: str              # display name in English
    native_name: str       # display name in the language itself (the app's selector shows it)
    stt_code: str          # pinned speech-to-text language (OpenAI transcribe `languages[]`)
    tts_code: str          # Sarvam target_language_code
    prompt_name: str       # the language as the model prompt names it
    has_templates: bool    # fixed code-written replies exist in this language
    selectable: bool = True


LANGUAGES: Dict[str, Language] = {
    "hi": Language("hi", "Hindi", "हिन्दी", stt_code="hi", tts_code="hi-IN",
                   prompt_name="Hindi (Hinglish in Roman script is fine)", has_templates=True),
    "en": Language("en", "English", "English", stt_code="en", tts_code="en-IN", prompt_name="English",
                   has_templates=True),
}

_FALLBACK_LOGGED: set = set()      # (conversation_id, code): "templates=fallback_en" logged once per conversation
_FALLBACK_LOCK = threading.Lock()
_FALLBACK_MAX = 5000


def normalize_choice(value: Any) -> str:
    """The user's choice -> "auto" or a selectable code from LANGUAGES. Unknown / missing / bad type -> "auto"."""
    if not isinstance(value, str):
        return AUTO
    code = value.strip().lower()[:10]
    lang = LANGUAGES.get(code)
    return code if lang is not None and lang.selectable else AUTO


def chosen(choice: Optional[str]) -> Optional[Language]:
    """The chosen Language, or None for auto."""
    return LANGUAGES.get(normalize_choice(choice))


def template_lang(choice: Optional[str], conversation_id: Optional[str] = None) -> Optional[str]:
    """The template key ("hi" / "en") for a chosen language, or None for auto (the caller detects it as before).
    A language without templates -> "en", logged once per conversation."""
    lang = chosen(choice)
    if lang is None:
        return None
    if lang.has_templates:
        return lang.code
    key = (conversation_id or "-", lang.code)
    with _FALLBACK_LOCK:
        first = key not in _FALLBACK_LOGGED
        if first:
            if len(_FALLBACK_LOGGED) >= _FALLBACK_MAX:
                _FALLBACK_LOGGED.clear()
            _FALLBACK_LOGGED.add(key)
    if first:
        print(f"[LANG] templates=fallback_en lang={lang.code}", flush=True)
    return "en"


def stt_languages(choice: Optional[str]) -> Optional[list]:
    """The STT pin for a chosen language ([stt_code]), or None for auto (VOICE_STT_LANGUAGES / auto-detect)."""
    lang = chosen(choice)
    return [lang.stt_code] if lang is not None else None


def tts_code(choice: Optional[str]) -> Optional[str]:
    """Sarvam's language code for a chosen language, or None for auto (the reply's own words decide)."""
    lang = chosen(choice)
    return lang.tts_code if lang is not None else None


def reply_rule(choice: Optional[str]) -> Optional[str]:
    """The model prompt line for a chosen language, or None for auto (the prompt stays as it was)."""
    lang = chosen(choice)
    if lang is None:
        return None
    return f"- Always reply in {lang.prompt_name}, whatever language the user speaks."
