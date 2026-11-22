import { getAuthToken, getWsBaseUrl } from '../config/apiConfig';

/** Messages from /ws/voice (see backend/voice/messages.py). */
export type VoiceServerMessage =
  | { type: 'ready' }
  | { type: 'recording'; turn_id: string }
  | {
      type: 'transcript';
      turn_id: string;
      text: string;
      language: string | null;
      duration_ms: number;
      latency_ms: number;
      truncated: boolean;
    }
  | {
      type: 'reply';
      turn_id: string;
      reply_text: string;
      reply_audio_base64: string | null;
      mime: string;
      tts_ms: number;
      ui_actions?: Array<{ type: string; to?: string; [key: string]: unknown }>;
      action?: string; // navigate:<page> | map_focus | where | answer | weather | decline | unclear | list_trips | open_trip | reply | error
      llm_ms?: number;
      tool_ms?: number;
      /** Small on-screen text, never spoken (e.g. "Details badal sakti hain."). */
      note?: string | null;
      /** "Google Maps" when the note is Google Maps content (attribution shown with it). */
      note_attribution?: string;
      /** Step 4/5: show the Confirm card (title: e.g. "Add this expense?"). */
      pending_confirmation?: { id: string; summary: string; title?: string } | null;
    }
  | {
      type: 'confirm_result';
      pending_id: string | null;
      ok: boolean;
      reply_text: string;
      ui_actions?: Array<{ type: string; [key: string]: unknown }>;
    }
  | { type: 'error'; code: string; message: string; turn_id?: string }
  | { type: 'closed'; code: number };

type Listener = (msg: VoiceServerMessage) => void;

const CLOSE_UNAUTHORIZED = 4401;
const CLOSE_FORBIDDEN_ORIGIN = 4403;
const MAX_RECONNECT_DELAY_MS = 10_000;

/**
 * The voice pipeline's own socket, separate from wsClient's /ws/app.
 * Login: the session cookie when the browser sends it, otherwise an {type:'auth'} first message.
 * Reconnects on unexpected drops while the app still wants it.
 */
class VoiceSocket {
  private ws: WebSocket | null = null;
  private readyPromise: Promise<void> | null = null;
  private listeners = new Set<Listener>();
  private wanted = false;
  private reconnectDelay = 1000;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  onMessage(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private emit(msg: VoiceServerMessage) {
    this.listeners.forEach((fn) => fn(msg));
  }

  isReady(): boolean {
    return !!this.ws && this.ws.readyState === WebSocket.OPEN && this.readyPromise !== null;
  }

  /** Opens the socket (if needed) and resolves once the server has accepted the login. */
  ensureOpen(): Promise<void> {
    this.wanted = true;
    if (this.readyPromise) return this.readyPromise;

    this.readyPromise = new Promise<void>((resolve, reject) => {
      let settled = false;
      const ws = new WebSocket(getWsBaseUrl('/ws/voice'));
      ws.binaryType = 'arraybuffer';
      this.ws = ws;

      ws.onopen = () => {
        // Harmless if the cookie already logged us in.
        ws.send(JSON.stringify({ type: 'auth', token: getAuthToken() || '' }));
      };

      ws.onmessage = (event) => {
        if (typeof event.data !== 'string') return;
        let msg: VoiceServerMessage;
        try {
          msg = JSON.parse(event.data);
        } catch {
          return;
        }
        if (!settled && msg.type === 'ready') {
          settled = true;
          this.reconnectDelay = 1000;
          resolve();
        } else if (!settled && msg.type === 'error') {
          settled = true;
          reject(new Error(msg.message));
        }
        this.emit(msg);
      };

      ws.onclose = (event) => {
        if (this.ws === ws) {
          this.ws = null;
          this.readyPromise = null;
        }
        if (!settled) {
          settled = true;
          reject(new Error(event.code === CLOSE_UNAUTHORIZED ? 'Your login has expired. Please log in again.' : 'Voice connection failed.'));
        }
        this.emit({ type: 'closed', code: event.code });
        const permanent = event.code === CLOSE_UNAUTHORIZED || event.code === CLOSE_FORBIDDEN_ORIGIN;
        if (this.wanted && !permanent) this.scheduleReconnect();
      };
    });
    // Callers handle the rejection; avoid an unhandled-rejection warning for background reconnects.
    this.readyPromise.catch(() => {});
    return this.readyPromise;
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) return;
    const delay = this.reconnectDelay;
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, MAX_RECONNECT_DELAY_MS);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this.wanted && !this.readyPromise) this.ensureOpen().catch(() => {});
    }, delay);
  }

  private sendJson(payload: object): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(payload));
    return true;
  }

  /**
   * tripId: the open trip (the server ownership-checks it; not yours = none), or null.
   * location: the user's position for "how far is X" (rounded; used for that turn only), or null.
   * screenPlace (step 5): the place page on screen, so "yeh jagah save karo" knows it (server checks the shape).
   */
  start(conversationId: string, screen: string, tripId: string | null = null, location: [number, number] | null = null,
    screenPlace: { place_id: string; name: string; address?: string } | null = null): boolean {
    const loc = location && Number.isFinite(location[0]) && Number.isFinite(location[1])
      ? { lat: Math.round(location[0] * 1e5) / 1e5, lng: Math.round(location[1] * 1e5) / 1e5 }
      : undefined;
    return this.sendJson({ type: 'start', conversation_id: conversationId, screen, trip_id: tripId, location: loc,
      screen_place: screenPlace });
  }

  sendAudio(chunk: ArrayBuffer) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(chunk);
  }

  stop(): boolean {
    return this.sendJson({ type: 'stop' });
  }

  /** Step 4: the Confirm card's buttons (Confirm runs the same action as saying "haan"). */
  /** tripId: the trip open now; a pending made for the open trip is refused if another trip is open (server-checked). */
  confirm(conversationId: string, pendingId: string, tripId: string | null = null): boolean {
    return this.sendJson({ type: 'confirm', conversation_id: conversationId, pending_id: pendingId, trip_id: tripId });
  }

  cancel(conversationId: string, pendingId: string): boolean {
    return this.sendJson({ type: 'cancel', conversation_id: conversationId, pending_id: pendingId });
  }

  /** The wizard created the trip (e.g. Proceed tapped): the voice draft can go. */
  draftDone(conversationId: string): boolean {
    return this.sendJson({ type: 'draft_done', conversation_id: conversationId });
  }

  /** Ends the voice session (test-only saving merges the session's audio) and closes the socket. */
  close() {
    this.wanted = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.sendJson({ type: 'end_session' });
    this.ws?.close(1000);
    this.ws = null;
    this.readyPromise = null;
  }
}

export const voiceSocket = new VoiceSocket();
