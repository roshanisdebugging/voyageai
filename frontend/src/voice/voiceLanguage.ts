/**
 * The voice assistant's language, chosen by the user (backend: voice/languages.py).
 *
 * "auto" (default): as before, the assistant answers in the language the user spoke.
 * "hi" / "en": STT, the code-written replies, the model and the spoken voice all use that language.
 * Only the voice changes; the app's written screens stay as they are.
 *
 * Kept in the browser (localStorage key VOICE_LANGUAGE_KEY; main.tsx keeps it through its storage wipe) and sent
 * with every voice turn ("start") and every Confirm / Cancel tap. A change applies from the next turn.
 * The account has a profile field `preferredLanguage`, but it is the app's language and is "en" for every account,
 * so using it would silently force English replies on everyone: the voice choice is stored on its own.
 */

export type VoiceLanguage = 'auto' | 'hi' | 'en';

export const VOICE_LANGUAGE_KEY = 'cruiser_voice_language';
export const VOICE_LANGUAGE_CHANGED = 'voyage:voice-language';

/** In the order the selectors show them. Labels are each language's own name. */
export const VOICE_LANGUAGES: { id: VoiceLanguage; label: string; short: string; spoken: string }[] = [
  { id: 'auto', label: 'Auto', short: 'Auto', spoken: 'Auto (the language you speak)' },
  { id: 'hi', label: 'हिन्दी', short: 'हि', spoken: 'Hindi' },
  { id: 'en', label: 'English', short: 'EN', spoken: 'English' },
];

/** Anything else (old / tampered storage) -> "auto". */
export function sanitizeVoiceLanguage(value: unknown): VoiceLanguage {
  return value === 'hi' || value === 'en' || value === 'auto' ? value : 'auto';
}

type StorageLike = Pick<Storage, 'getItem' | 'setItem'> | null | undefined;

function storage(): StorageLike {
  try {
    return typeof window !== 'undefined' ? window.localStorage : undefined;
  } catch {
    return undefined;   // blocked storage (private window): the choice lives for this page only
  }
}

let memoryValue: VoiceLanguage = 'auto';

export function getVoiceLanguage(store: StorageLike = storage()): VoiceLanguage {
  try {
    const saved = store?.getItem(VOICE_LANGUAGE_KEY);
    if (saved !== null && saved !== undefined) return sanitizeVoiceLanguage(saved);
  } catch {
    /* fall through to the in-memory value */
  }
  return memoryValue;
}

export function setVoiceLanguage(value: VoiceLanguage, store: StorageLike = storage()): VoiceLanguage {
  const next = sanitizeVoiceLanguage(value);
  memoryValue = next;
  try {
    store?.setItem(VOICE_LANGUAGE_KEY, next);
  } catch {
    /* kept in memory only */
  }
  try {
    if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(VOICE_LANGUAGE_CHANGED, { detail: next }));
  } catch {
    /* no window (tests) */
  }
  return next;
}

/** The small control by the mic: one tap moves to the next option (Auto -> हिन्दी -> English -> Auto). */
export function nextVoiceLanguage(current: VoiceLanguage): VoiceLanguage {
  const i = VOICE_LANGUAGES.findIndex(o => o.id === current);
  return VOICE_LANGUAGES[(i + 1) % VOICE_LANGUAGES.length].id;
}

export function voiceLanguageOption(id: VoiceLanguage) {
  return VOICE_LANGUAGES.find(o => o.id === id) ?? VOICE_LANGUAGES[0];
}
