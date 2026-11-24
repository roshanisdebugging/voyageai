import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useLocation, useNavigate } from 'react-router-dom';
import { Loader2, Mic, Square } from 'lucide-react';
import { useAuth } from '../auth/AuthContext';
import { useToast } from '../components/common/UndoToast';
import { voiceSocket, type VoiceServerMessage } from './voiceSocket';
import { MAX_RECORDING_MS, useVoiceRecorder } from './useVoiceRecorder';
import { TestTranscriptPanel, type PanelEntry } from './TestTranscriptPanel';
import { replyPlayer } from './replyPlayer';
import { runUiActions, type UiActionHandlers } from './uiActions';
import { ConfirmCard } from './ConfirmCard';
import { isReviewShowing, requestSubmitReview, TRIP_CREATED } from './reviewState';
import { useTrip } from '../features/trip/TripContext';
import { useNavigation } from '../context/NavigationContext';
import { useApp } from '../context/AppContext';
import { deviceLocation, useDeviceLocation } from '../services/useDeviceLocation';
import { GoogleMapsAttribution } from '../components/common/GoogleMapsAttribution';
import { useAppDispatch } from '../store/hooks';
import { fetchSavedPlaces } from '../store/reducers/savedPlacesSlice';
import { fetchUserTrips } from '../store/reducers/tripsSlice';
import { wsClient } from '../services/wsClient';
import { getScreenPlace, SAVED_PLACES_CHANGED } from './screenPlace';

const SHOW_TEST_PANEL = import.meta.env.VITE_VOICE_TEST_TRANSCRIPT === 'true';
const REPLY_TIMEOUT_MS = 30_000; // covers STT + TTS: only times out if no "reply" arrives

type Phase = 'idle' | 'starting' | 'recording' | 'waiting' | 'speaking';

const newId = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;

/**
 * Floating mic (voicefirst.md steps 1 + 1b): tap to start, tap to stop, 30 s cap.
 * Streams 16 kHz PCM over /ws/voice, shows what speech-to-text heard in the test panel, then plays the
 * spoken reply. Tapping while it speaks stops the reply and starts a new recording (barge-in).
 */
type MicPlace = 'shell' | 'wizard';

const MicButtonInner: React.FC<{ raised: boolean; inlineTarget: HTMLElement | null; place: MicPlace }> = ({ raised, inlineTarget, place }) => {
  const location = useLocation();
  const navigate = useNavigate();
  const { currentTrip, trips, setCurrentTripId, refetchItinerary, fetchPackageData } = useTrip();
  // The device's current location, sent with "start" for "how far is X" (that turn only); read when the app opens
  const deviceLoc = useDeviceLocation();
  const { setMapFocusTarget } = useNavigation();
  const { openSwapAssistant } = useApp();
  const dispatch = useAppDispatch();
  // The socket handler is subscribed once: read the latest trips / setters through a ref.
  const tripApiRef = useRef({ trips, currentTrip, setCurrentTripId, setMapFocusTarget, refetchItinerary, fetchPackageData, openSwapAssistant, dispatch });
  useEffect(() => {
    tripApiRef.current = { trips, currentTrip, setCurrentTripId, setMapFocusTarget, refetchItinerary, fetchPackageData, openSwapAssistant, dispatch };
  }, [trips, currentTrip, setCurrentTripId, setMapFocusTarget, refetchItinerary, fetchPackageData, openSwapAssistant, dispatch]);
  const { showToast } = useToast();
  const [phase, setPhase] = useState<Phase>('idle');
  const [entries, setEntries] = useState<PanelEntry[]>([]);
  const [remaining, setRemaining] = useState(MAX_RECORDING_MS / 1000);
  const [note, setNote] = useState<string | null>(null);
  const [noteAttribution, setNoteAttribution] = useState<string | null>(null);
  // Step 4: the Confirm card ({id, summary} from the server); Confirm == saying "haan".
  const [confirmCard, setConfirmCard] = useState<{ id: string; summary: string; title?: string } | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const confirmKindRef = useRef<'confirm' | 'cancel' | null>(null);
  const noteTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (noteTimerRef.current) clearTimeout(noteTimerRef.current); }, []);

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

  // reason: the technical why (code / status / class names) for the test panel only; users see the message.
  const report = useCallback((message: string, reason?: string) => {
    if (SHOW_TEST_PANEL) {
      const text = reason ? `${message} ✖ ${reason}` : message;
      setEntries((prev) => [{ id: newId(), kind: 'error' as const, text, at: Date.now() }, ...prev].slice(0, 50));
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

  // Step 5: reload what a voice change touched (the open screen updates without a manual reload).
  const refresh = useCallback((what: 'itinerary' | 'expenses' | 'saved_places') => {
    const api = tripApiRef.current;
    const tripId = api.currentTrip?.id;
    if (what === 'itinerary' && tripId) {
      void api.refetchItinerary(tripId);
      // The trip itself may have changed too (its budget: voice set_trip_budget / optimize_budget).
      void api.dispatch(fetchUserTrips({ force: true }));
    }
    else if (what === 'expenses' && tripId) void api.fetchPackageData(tripId);
    else if (what === 'saved_places') {
      void api.dispatch(fetchSavedPlaces({ force: true }));
      window.dispatchEvent(new Event(SAVED_PLACES_CHANGED));
    }
  }, []);

  // ui_action handlers shared by voice replies and Confirm-button results.
  const handlers = useCallback((): UiActionHandlers => ({
    navigate: (to) => navigate(to),
    // Step 3: "Hawa Mahal dikhao" -> the map shows a pin and the distance (the navigate to /map follows).
    mapFocus: ({ lat, lng, name, placeId }) => tripApiRef.current.setMapFocusTarget({
      id: placeId || `voice-${lat}-${lng}`, name, coordinates: [lat, lng], zoom: 15, highlight: true, pin: true,
    }),
    // "Hawa Mahal ke paas restaurant": the places become the map's markers and cards (navigate to /map follows).
    mapResults: ({ title, places }) => tripApiRef.current.setMapFocusTarget({
      id: `voice-results-${Date.now()}`, name: title, coordinates: [places[0].lat, places[0].lng],
      results: { title, places },
    }),
    // Only an ID from the user's own loaded trips; anything else is ignored.
    openTrip: (tripId) => {
      if (!tripApiRef.current.trips.some((t) => t.id === tripId)) return false;
      tripApiRef.current.setCurrentTripId(tripId);
      return true;
    },
    // Step 4: the filled, editable review page (the existing wizard); "haan" presses its Proceed.
    openReview: (prefill) => navigate('/trips/new', { state: { prefill } }),
    submitReview: requestSubmitReview,
    // Step 5: the existing swap sheet for the open trip's activity; the sheet's own Confirm applies it.
    // Only for one of the user's own loaded trips (the voice action may name a trip that isn't the open one).
    openSwap: ({ tripId, activityId, activityName, dayNumber }) => {
      const trip = tripApiRef.current.trips.find((t) => t.id === tripId);
      if (!trip) return;
      tripApiRef.current.openSwapAssistant({
        tripId: trip.id, activityId, activityName, selectedDay: dayNumber, destination: trip.destination?.name,
      });
    },
    refresh,
    // Small actions: Undo (tap only, 5 s) runs the allowlisted /ws/app action, then reloads the screen.
    undoToast: ({ message, action, payload }) => showToast({
      message,
      undo: async () => {
        await wsClient.sendRequest(action, payload);
        refresh(action === 'trips:set_activity_done' ? 'itinerary' : 'saved_places');
      },
    }),
  }), [navigate, refresh, showToast]);

  // Server messages
  useEffect(() => {
    return voiceSocket.onMessage((msg: VoiceServerMessage) => {
      if (msg.type === 'transcript') {
        // The turn continues: the reply (step 1b) follows. The reply timer keeps running.
        const roundTripMs = stopAtRef.current ? Math.round(performance.now() - stopAtRef.current) : undefined;
        setEntries((prev) => [{
          id: msg.turn_id,
          kind: 'transcript' as const,
          text: msg.text,
          language: msg.language,
          durationMs: msg.duration_ms,
          sttMs: msg.latency_ms,
          roundTripMs,
          truncated: msg.truncated,
          at: Date.now(),
        }, ...prev].slice(0, 50));
      } else if (msg.type === 'reply') {
        clearReplyTimer();
        const turnId = msg.turn_id;
        const update = (patch: Partial<PanelEntry>) =>
          setEntries((prev) => prev.map((e) => (e.id === turnId ? { ...e, ...patch } : e)));
        const navTo = (msg.ui_actions || []).find((a) => a.type === 'navigate')?.to;
        update({
          replyText: msg.reply_text, ttsMs: msg.tts_ms, action: msg.action, llmMs: msg.llm_ms, navTo,
          errorCode: msg.error_code, errorDetail: msg.error_detail, ttsError: msg.tts_error,
        });
        // Why a turn failed (LLM / tool / Sarvam): the reason is in the console, not just "error".
        if (msg.action === 'error' || msg.tts_error) {
          console.error('[voice] turn failed', {
            turnId, action: msg.action, error_code: msg.error_code, error_detail: msg.error_detail,
            tts_error: msg.tts_error, llm_ms: msg.llm_ms, tts_ms: msg.tts_ms,
          });
        }
        // Step 4: a reply with a pending confirmation shows the Confirm card; any other reply closes it.
        const pc = msg.pending_confirmation;
        setConfirmCard(pc && typeof pc.id === 'string' && typeof pc.summary === 'string'
          ? { id: pc.id, summary: pc.summary.slice(0, 400), title: typeof pc.title === 'string' ? pc.title.slice(0, 60) : undefined }
          : null);
        setConfirmBusy(false);
        if (phaseRef.current !== 'waiting') return; // the user already moved on (e.g. started recording)
        // A note (e.g. "Details badal sakti hain.") is shown as small text for a few seconds, never spoken.
        if (noteTimerRef.current) clearTimeout(noteTimerRef.current);
        setNote(typeof msg.note === 'string' && msg.note ? msg.note.slice(0, 120) : null);
        setNoteAttribution(msg.note && msg.note_attribution === 'Google Maps' ? 'Google Maps' : null);
        if (msg.note) noteTimerRef.current = setTimeout(() => setNote(null), 6000);
        // Step 2: run the agent's ui_actions FIRST (e.g. open the map), then speak.
        runUiActions(msg.ui_actions, handlers());
        if (!msg.reply_audio_base64) {
          setPhaseBoth('idle'); // the error ("Couldn't play the reply.") follows as its own message
          return;
        }
        setPhaseBoth('speaking');
        replyPlayer
          .play(msg.reply_audio_base64, msg.mime, () => {
            if (stopAtRef.current) update({ totalMs: Math.round(performance.now() - stopAtRef.current) });
          })
          .catch(() => report("Couldn't play the reply."))
          .finally(() => {
            if (phaseRef.current === 'speaking') setPhaseBoth('idle');
          });
      } else if (msg.type === 'confirm_result') {
        // Answer to the Confirm / Cancel buttons.
        const kind = confirmKindRef.current;
        confirmKindRef.current = null;
        setConfirmBusy(false);
        setConfirmCard(null);
        if (msg.ok && kind === 'confirm') {
          runUiActions(msg.ui_actions, handlers());
          // Steps 5/6: a confirmed expense / rebuild / smart change says what happened (the trip wizard shows its own progress).
          if (msg.reply_text && !(msg.ui_actions || []).some((a) => a.type === 'submit_review')) showToast({ message: msg.reply_text });
        } else if (msg.ok && kind === 'cancel') {
          report(msg.reply_text || 'Okay, nothing changed.');
        } else if (!msg.ok && kind === 'confirm') {
          report(msg.reply_text || 'Nothing to confirm any more.');
        }
      } else if (msg.type === 'error') {
        console.error('[voice] error', { code: msg.code, message: msg.message, detail: msg.detail, turnId: msg.turn_id });
        const reason = msg.detail ? `${msg.code}: ${msg.detail}` : msg.code;
        if (msg.code === 'tts_failed') {
          report(msg.message, reason); // the turn itself worked; the state was already handled by "reply"
          return;
        }
        clearReplyTimer();
        report(msg.message, reason);
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
  }, [report, recorder, handlers, showToast]);

  // Step 4: the wizard created the trip (Proceed by tap or by voice): the voice draft goes too.
  useEffect(() => {
    const onCreated = () => {
      setConfirmCard(null);
      voiceSocket.draftDone(conversationId.current);
    };
    window.addEventListener(TRIP_CREATED, onCreated);
    return () => window.removeEventListener(TRIP_CREATED, onCreated);
  }, []);

  const onConfirmTap = () => {
    if (!confirmCard || confirmBusy) return;
    confirmKindRef.current = 'confirm';
    setConfirmBusy(true);
    if (!voiceSocket.confirm(conversationId.current, confirmCard.id, currentTrip?.id ?? null)) {
      setConfirmBusy(false);
      confirmKindRef.current = null;
      report('Voice connection lost. Tap Proceed on the review page instead.');
    }
  };
  const onCancelTap = () => {
    if (!confirmCard || confirmBusy) return;
    confirmKindRef.current = 'cancel';
    setConfirmBusy(true);
    if (!voiceSocket.cancel(conversationId.current, confirmCard.id)) {
      setConfirmBusy(false);
      setConfirmCard(null);
      confirmKindRef.current = null;
    }
  };

  // Close the voice session and stop any reply when the button goes away (logout, leaving the app).
  useEffect(() => () => {
    clearReplyTimer();
    replyPlayer.close();
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
    // Barge-in: tapping while the reply plays stops it and starts a new recording.
    if (phaseRef.current === 'speaking') {
      replyPlayer.stop();
      setPhaseBoth('idle');
    }
    if (phaseRef.current !== 'idle') return;

    // Inside the tap, before any await: unlock reply playback (iOS) and stop any playing reply.
    replyPlayer.prime();
    replyPlayer.stop();
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
    // Step 4: on the wizard's review step the agent must know that "haan" means Proceed.
    const screen = location.pathname === '/trips/new' && isReviewShowing() ? '/trips/new#review' : location.pathname;
    const screenPlace = location.pathname.startsWith('/details/') ? getScreenPlace() : null;
    void deviceLocation.ensureFresh(); // mic tap: re-read if older than a minute (for the next turn; never blocks)
    if (!voiceSocket.start(conversationId.current, screen, currentTrip?.id ?? null, deviceLoc.reading ?? null, screenPlace)) {
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
    : phase === 'waiting' ? 'Working on it'
    : phase === 'speaking' ? 'Speaking. Tap to interrupt.'
    : phase === 'starting' ? 'Starting microphone'
    : 'Start voice input';

  const inline = inlineTarget !== null;
  // The wizard has no bottom nav: sit above its Proceed button, and above the Confirm card while it shows.
  const micBottom = place === 'wizard'
    ? `calc(env(safe-area-inset-bottom, 0px) + ${confirmCard ? 236 : 104}px)`
    : `calc(var(--bottom-nav-h) + env(safe-area-inset-bottom, 0px) + ${raised ? 80 : 12}px)`;
  const button = (
    <button
      type="button"
      onClick={handleTap}
      aria-label={label}
      title={label}
      aria-pressed={phase === 'recording'}
      disabled={phase === 'waiting' || phase === 'starting'}
      className={`${inline ? 'size-11 shrink-0 rounded-lg' : 'fixed z-[var(--z-floating)] right-4 size-14 rounded-full shadow-lg'} flex flex-col items-center justify-center press-scale transition-colors disabled:cursor-wait ${
        phase === 'recording'
          ? 'bg-rose-600 text-white ring-4 ring-rose-300/60 animate-pulse'
          : phase === 'speaking'
          ? 'bg-[#355F58] dark:bg-emerald-600 text-white ring-4 ring-[#355F58]/30 dark:ring-emerald-400/30'
          : 'bg-white dark:bg-zinc-900 text-[#355F58] dark:text-emerald-400 border border-[#D9DEDA] dark:border-zinc-700'
      }`}
      style={inline ? undefined : { bottom: micBottom }}
    >
      {phase === 'recording' ? (
        <>
          <Square className="w-4 h-4 fill-white" aria-hidden="true" />
          <span className="text-[10px] font-bold leading-none mt-0.5 tabular-nums">{remaining}s</span>
        </>
      ) : phase === 'speaking' ? (
        <span className="flex items-center gap-[3px]" aria-hidden="true">
          {[0, 150, 300, 450].map((delay) => (
            <span key={delay} className="voice-wave-bar" style={{ animationDelay: `${delay}ms` }} />
          ))}
        </span>
      ) : phase === 'idle' ? (
        <Mic className={inline ? 'size-5' : 'size-6'} aria-hidden="true" />
      ) : (
        <Loader2 className="w-6 h-6 animate-spin" aria-hidden="true" />
      )}
    </button>
  );

  return (
    <>
      {SHOW_TEST_PANEL && <TestTranscriptPanel entries={entries} onClear={() => setEntries([])} />}
      {confirmCard && (
        <ConfirmCard
          summary={confirmCard.summary}
          title={confirmCard.title}
          busy={confirmBusy}
          onConfirm={onConfirmTap}
          onCancel={onCancelTap}
          bottom={place === 'wizard' ? 'calc(env(safe-area-inset-bottom, 0px) + 12px)' : undefined}
        />
      )}
      {note && (
        <p
          role="status"
          data-voice-note
          className="fixed z-[var(--z-floating)] right-4 max-w-[220px] px-2.5 py-1 rounded-lg bg-white/95 dark:bg-zinc-900/95 border border-[#D9DEDA] dark:border-zinc-700 text-[11px] text-[#5F6863] dark:text-zinc-400 shadow-sm"
          // The map sets --mic-note-bottom so the note stays off Google's attribution.
          style={{ bottom: `var(--mic-note-bottom, calc(${micBottom} + 64px))` }}
        >
          {note}
          {noteAttribution && <GoogleMapsAttribution className="block mt-0.5" />}
        </p>
      )}
      {inlineTarget ? createPortal(button, inlineTarget) : button}
    </>
  );
};

/**
 * Only after login. `raised` stacks it above the floating AI button when that one is shown; `place` is "wizard" on
 * the full-screen trip wizard. Mounted once above the routes (see micLayout.tsx), so page changes keep the socket.
 */
export const MicButton: React.FC<{ raised?: boolean; inlineTarget?: HTMLElement | null; place?: MicPlace }> = ({
  raised = true,
  inlineTarget = null,
  place = 'shell',
}) => {
  const { isAuthenticated } = useAuth();
  return isAuthenticated ? <MicButtonInner raised={raised} inlineTarget={inlineTarget} place={place} /> : null;
};
