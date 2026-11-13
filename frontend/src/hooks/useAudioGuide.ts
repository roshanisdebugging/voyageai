import { useState, useRef, useCallback } from 'react';
import { getApiBaseUrl, DEFAULT_FETCH_OPTIONS } from '../config/apiConfig';

export const useAudioGuide = () => {
  const [isPlaying, setIsPlaying] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const stopAudio = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      audioRef.current = null;
    }
    setIsPlaying(false);
  }, []);

  const playBase64Audio = useCallback((base64Data: string) => {
    stopAudio();
    try {
      const audioUrl = base64Data.startsWith('data:audio') ? base64Data : `data:audio/mp3;base64,${base64Data}`;
      const audio = new Audio(audioUrl);
      audioRef.current = audio;

      audio.onended = () => {
        setIsPlaying(false);
        audioRef.current = null;
      };

      audio.onerror = (e) => {
        console.error('Audio playback error:', e);
        setIsPlaying(false);
        audioRef.current = null;
      };

      audio.play();
      setIsPlaying(true);
    } catch (err) {
      console.error('Failed to play base64 audio:', err);
      setIsPlaying(false);
    }
  }, [stopAudio]);

  const synthesizeAndPlay = useCallback(async (
    text: string,
    targetLanguageCode: string = 'hi-IN',
    speaker: string = 'meera',
    poiId?: string
  ) => {
    if (!text || !text.trim()) return;
    setIsLoading(true);
    try {
      const baseUrl = getApiBaseUrl();
      const res = await fetch(`${baseUrl}/api/tts/synthesize`, {
        ...DEFAULT_FETCH_OPTIONS,
        method: 'POST',
        body: JSON.stringify({
          text: text.slice(0, 480),
          target_language_code: targetLanguageCode,
          speaker: speaker,
          poi_id: poiId
        })
      });

      if (res.ok) {
        const data = await res.json();
        if (data.audio_base64) {
          playBase64Audio(data.audio_base64);
        }
      } else {
        console.warn('TTS Synthesis request returned non-200 status:', res.status);
      }
    } catch (err) {
      console.error('Failed to synthesize Sarvam AI speech:', err);
    } finally {
      setIsLoading(false);
    }
  }, [playBase64Audio]);

  return { playBase64Audio, synthesizeAndPlay, stopAudio, isPlaying, isLoading };
};
