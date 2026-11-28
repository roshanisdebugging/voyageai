import { useEffect, useState } from 'react';
import { getVoiceLanguage, setVoiceLanguage, VOICE_LANGUAGE_CHANGED, type VoiceLanguage } from './voiceLanguage';

/** The voice language, kept in step between the mic control and Settings (same tab: an event; the value is stored). */
export function useVoiceLanguage(): [VoiceLanguage, (next: VoiceLanguage) => void] {
  const [value, setValue] = useState<VoiceLanguage>(() => getVoiceLanguage());
  useEffect(() => {
    const onChange = () => setValue(getVoiceLanguage());
    window.addEventListener(VOICE_LANGUAGE_CHANGED, onChange);
    return () => window.removeEventListener(VOICE_LANGUAGE_CHANGED, onChange);
  }, []);
  return [value, next => setValue(setVoiceLanguage(next))];
}
