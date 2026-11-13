import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { Loader2, Mic, Square } from 'lucide-react';
import { useAuth } from '../auth/AuthContext';
import { useToast } from '../components/common/UndoToast';
import { voiceSocket, type VoiceServerMessage } from './voiceSocket';
import { MAX_RECORDING_MS, useVoiceRecorder } from './useVoiceRecorder';
import { TestTranscriptPanel, type PanelEntry } from './TestTranscriptPanel';

const SHOW_TEST_PANEL = import.meta.env.VITE_VOICE_TEST_TRANSCRIPT === 'true';
const REPLY_TIMEOUT_MS = 30_000;

type Phase = 'idle' | 'starting' | 'recording' | 'waiting';

const newId = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;

/**
 * Floating mic (voicefirst.md step 1): tap to start, tap to stop, 30 s cap.
 * Streams 16 kHz PCM over /ws/voice and shows what Groq heard in the test panel.
 */
const MicButtonInner: React.FC<{ raised: boolean }> = ({ raised }) => {
  const location = useLocation();
  const { showToast } = useToast();
  const [phase, setPhase] = useState<Phase>('idle');
  const [entries, setEntries] = useState<PanelEntry[]>([]);
  const [remaining, setRemaining] = useState(MAX_RECORDING_MS / 1000);

  const phaseRef = useRef<Phase>('idle');
  const conversationId = useRef(`conv_${newId()}`);
  const streamingRef = useRef(false);          // "start" sent: chunks go straight to the socket
  const queuedRef = useRef<ArrayBuffer[]>([]);  // chunks captured before the socket was ready
  const stopAtRef = useRef(0);
  const replyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const setPhaseBoth = (p: Phase) => {
    phaseRef.current = p;
    setPhase(p);
  };

  const report = useCallback((message: string) => {
    if (SHOW_TEST_PANEL) {
      setEntries((prev) => [{ id: newId(), kind: 'error' as const, text: message, at: Date.now() }, ...prev].slice(0, 50));
    } else {
      showToast({ message, tone: 'error' });
    }
  }, [showToast]);

  const recorder = useVoiceRecorder({
    onChunk: (chunk) => {
      if (streamingRef.current) voiceSocket.sendAudio(chunk);
      else queuedRef.current.push(chunk);
    },
    onAutoStop: () => sendStop(),
  });

  const clearReplyTimer = () => {
    if (replyTimerRef.current) clearTimeout(replyTimerRef.current);
    replyTimerRef.current = null;
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  function sendStop() {
    streamingRef.current = false;
    queuedRef.current = [];
    if (!voiceSocket.stop()) {
      report('Voice connection lost. Please try again.');
      setPhaseBoth('idle');
      return;
    }
    stopAtRef.current = performance.now();
    setPhaseBoth('waiting');
    clearReplyTimer();
    replyTimerRef.current = setTimeout(() => {
      if (phaseRef.current === 'waiting') {
        report('No answer from the server. Please try again.');
        setPhaseBoth('idle');
      }
    }, REPLY_TIMEOUT_MS);
  }

  // Server messages
  useEffect(() => {
    return voiceSocket.onMessage((msg: VoiceServerMessage) => {
      if (msg.type === 'transcript') {
        clearReplyTimer();
        const roundTripMs = stopAtRef.current ? Math.round(performance.now() - stopAtRef.current) : undefined;
        setEntries((prev) => [{
          id: msg.turn_id,
          kind: 'transcript' as const,
          text: msg.text,
          language: msg.language,
          durationMs: msg.duration_ms,
          groqMs: msg.latency_ms,
          roundTripMs,
          truncated: msg.truncated,
          at: Date.now(),
        }, ...prev].slice(0, 50));
        if (phaseRef.current === 'waiting') setPhaseBoth('idle');
      } else if (msg.type === 'error') {
        clearReplyTimer();
        report(msg.message);
        if (phaseRef.current === 'recording') {
          streamingRef.current = false;
          recorder.stop();
        }
        if (phaseRef.current !== 'starting') setPhaseBoth('idle');
      } else if (msg.type === 'closed') {
        if (phaseRef.current === 'recording' || phaseRef.current === 'waiting') {
          clearReplyTimer();
          streamingRef.current = false;
          recorder.stop();
          report(msg.code === 4401 ? 'Your login has expired. Please log in again.' : 'Voice connection lost. Please try again.');
          setPhaseBoth('idle');
        }
      }
    });
  }, [report, recorder]);

  // Close the voice session when the button goes away (logout, leaving the app).
  useEffect(() => () => {
    clearReplyTimer();
    voiceSocket.close();
  }, []);

  // 30 s countdown while recording
  useEffect(() => {
    if (phase !== 'recording' || !recorder.startedAt) return;
    const startedAt = recorder.startedAt;
    const tick = () => setRemaining(Math.max(0, Math.ceil((MAX_RECORDING_MS - (Date.now() - startedAt)) / 1000)));
    tick();
    const id = setInterval(tick, 250);
    return () => clearInterval(id);
  }, [phase, recorder.startedAt]);

  const handleTap = async () => {
    if (phaseRef.current === 'recording') {
      await recorder.stop(); // flushes the last chunk to the socket first
      sendStop();
      return;
    }
    if (phaseRef.current !== 'idle') return;

    setPhaseBoth('starting');
    queuedRef.current = [];
    streamingRef.current = false;
    // recorder.start() creates the AudioContext synchronously, inside this tap.
    const micReady = recorder.start();
    const socketReady = voiceSocket.ensureOpen();
    try {
      await Promise.all([micReady, socketReady]);
    } catch (err) {
      await recorder.stop();
      report((err as Error)?.message || "Couldn't start voice.");
      setPhaseBoth('idle');
      return;
    }
    if (!voiceSocket.start(conversationId.current, location.pathname)) {
      await recorder.stop();
      report('Voice connection lost. Please try again.');
      setPhaseBoth('idle');
      return;
    }
    // The server reads frames in order, so audio sent after "start" belongs to this recording.
    queuedRef.current.forEach((chunk) => voiceSocket.sendAudio(chunk));
    queuedRef.current = [];
    streamingRef.current = true;
    setRemaining(MAX_RECORDING_MS / 1000);
    setPhaseBoth('recording');
  };

  const label =
    phase === 'recording' ? `Stop recording, ${remaining} seconds left`
    : phase === 'waiting' ? 'Transcribing'
    : phase === 'starting' ? 'Starting microphone'
    : 'Start voice input';

  return (
    <>
      {SHOW_TEST_PANEL && <TestTranscriptPanel entries={entries} onClear={() => setEntries([])} />}
      <button
        type="button"
        onClick={handleTap}
        aria-label={label}
        title={label}
        aria-pressed={phase === 'recording'}
        disabled={phase === 'waiting' || phase === 'starting'}
        className={`fixed z-30 right-4 w-14 h-14 rounded-full shadow-lg flex flex-col items-center justify-center press-scale transition-colors disabled:cursor-wait ${
          phase === 'recording'
            ? 'bg-rose-600 text-white ring-4 ring-rose-300/60 animate-pulse'
            : 'bg-white dark:bg-zinc-900 text-[#355F58] dark:text-emerald-400 border border-[#D9DEDA] dark:border-zinc-700'
        }`}
        style={{ bottom: `calc(var(--bottom-nav-h) + env(safe-area-inset-bottom, 0px) + ${raised ? 80 : 12}px)` }}
      >
        {phase === 'recording' ? (
          <>
            <Square className="w-4 h-4 fill-white" aria-hidden="true" />
            <span className="text-[10px] font-bold leading-none mt-0.5 tabular-nums">{remaining}s</span>
          </>
        ) : phase === 'idle' ? (
          <Mic className="w-6 h-6" aria-hidden="true" />
        ) : (
          <Loader2 className="w-6 h-6 animate-spin" aria-hidden="true" />
        )}
      </button>
    </>
  );
};

/** Only after login. `raised` stacks it above the floating AI button when that one is shown. */
export const MicButton: React.FC<{ raised?: boolean }> = ({ raised = true }) => {
  const { isAuthenticated } = useAuth();
  return isAuthenticated ? <MicButtonInner raised={raised} /> : null;
};
