/**
 * VoyageAI — Persistent WebSocket Client Engine
 * Features: Exponential Backoff Reconnection, Replay Buffering, Dual Envelope Schemas (V4 RPC + Legacy)
 */

import { getAuthToken } from '../config/apiConfig';

export interface WsRequestFrame {
  id?: string;
  action?: string;
  payload?: any;
  // Legacy fields
  type?: 'request' | 'ping';
  reqname?: string;
  data?: any;
  requestId?: string;
  token?: string;
}

export interface WsResponseFrame {
  id?: string;
  action?: string;
  status?: number | 'success' | 'error';
  data?: any;
  error?: string | null;
  // Legacy fields
  type?: 'response' | 'event' | 'pong';
  reqname?: string;
  requestId?: string;
}

type EventListener = (data: any) => void;

interface PendingRequest {
  resolve: (val: any) => void;
  reject: (err: any) => void;
  timer: any;
  frame: WsRequestFrame;
}

const DEFAULT_TIMEOUT_MS = 20000;

import { getWsBaseUrl } from '../config/apiConfig';

class WebSocketClient {
  private ws: WebSocket | null = null;
  private url: string;
  private isConnecting: boolean = false;
  private reconnectTimer: any = null;
  private reconnectAttempts: number = 0;
  private baseDelay: number = 1000;
  private maxDelay: number = 30000;
  private backoffFactor: number = 1.5;

  private pendingRequests: Map<string, PendingRequest> = new Map();
  private offlineBuffer: WsRequestFrame[] = [];
  private eventListeners: Map<string, Set<EventListener>> = new Map();
  private isReadyPromise: Promise<void> | null = null;
  private resolveReady: (() => void) | null = null;

  constructor() {
    this.url = getWsBaseUrl('/ws/app');
    this.connect();
  }

  public getIsConnecting(): boolean {
    return this.isConnecting;
  }

  public connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    this.isConnecting = true;
    this.isReadyPromise = new Promise((resolve) => {
      this.resolveReady = resolve;
    });

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        console.log(`[WS] Connected to ${this.url} (Reset backoff attempts)`);
        this.isConnecting = false;
        this.reconnectAttempts = 0;

        if (this.resolveReady) {
          this.resolveReady();
        }

        this.flushOfflineBuffer();
      };

      this.ws.onmessage = (event) => {
        try {
          const frame: WsResponseFrame = JSON.parse(event.data);
          this.handleIncomingFrame(frame);
        } catch (err) {
          console.error('[WS] Invalid JSON frame received:', event.data, err);
        }
      };

      this.ws.onerror = (err) => {
        console.warn('[WS] Socket error:', err);
      };

      this.ws.onclose = () => {
        console.warn('[WS] Disconnected from server. Initiating exponential backoff reconnect...');
        this.isConnecting = false;
        this.scheduleReconnect();
      };
    } catch (err) {
      console.error('[WS] Failed to establish WebSocket connection:', err);
      this.isConnecting = false;
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;

    // Exponential Backoff with Jitter
    const backoffDelay = Math.min(
      this.maxDelay,
      this.baseDelay * Math.pow(this.backoffFactor, this.reconnectAttempts)
    );
    const jitter = Math.random() * 500;
    const totalDelay = Math.floor(backoffDelay + jitter);

    this.reconnectAttempts++;
    console.log(`[WS] Reconnecting in ${totalDelay}ms (Attempt #${this.reconnectAttempts})...`);

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, totalDelay);
  }

  private flushOfflineBuffer(): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;

    if (this.offlineBuffer.length > 0) {
      // Deduplicate buffered frames before replaying
      const uniqueFrames: WsRequestFrame[] = [];
      const seen = new Set<string>();
      for (let i = this.offlineBuffer.length - 1; i >= 0; i--) {
        const f = this.offlineBuffer[i];
        const key = `${f.action || f.reqname}:${JSON.stringify(f.payload || f.data)}`;
        if (!seen.has(key)) {
          seen.add(key);
          uniqueFrames.unshift(f);
        }
      }
      console.log(`[WS] Replaying ${uniqueFrames.length} unique buffered offline request(s)...`);
      this.offlineBuffer = [];

      for (const frame of uniqueFrames) {
        try {
          this.ws.send(JSON.stringify(frame));
        } catch (err) {
          console.error('[WS] Error replaying buffered frame:', err);
        }
      }
    }
  }

  private handleIncomingFrame(frame: WsResponseFrame): void {
    const reqId = frame.id || frame.requestId;
    const actionName = frame.action || frame.reqname;

    // 1. Check if frame matches a pending request ID
    if (reqId && this.pendingRequests.has(reqId)) {
      const pending = this.pendingRequests.get(reqId)!;
      clearTimeout(pending.timer);
      this.pendingRequests.delete(reqId);

      const isError =
        frame.status === 'error' ||
        (typeof frame.status === 'number' && frame.status >= 400) ||
        Boolean(frame.error);
      if (isError) {
        pending.reject(new Error(frame.error || 'WebSocket request failed'));
      } else {
        pending.resolve(frame.data);
      }
      return;
    }

    // 2. Event broadcast routing (e.g. trips:generation_completed)
    if (actionName) {
      const cleanAction = actionName.replace(/:reply$/, '').replace(/:response$/, '');
      const listeners = this.eventListeners.get(cleanAction) || this.eventListeners.get(actionName);
      if (listeners) {
        listeners.forEach((listener) => listener(frame.data));
      }
    }
  }

  private async ensureConnected(): Promise<void> {
    if (this.ws?.readyState === WebSocket.OPEN) return;
    if (!this.isReadyPromise) {
      this.connect();
    }
    await this.isReadyPromise;
  }

  /**
   * Main method to send a request over WebSocket and await the response frame
   */
  public async sendRequest<T = any>(reqname: string, data: any = {}, timeoutMs: number = DEFAULT_TIMEOUT_MS): Promise<T> {
    const requestId = 'req_' + Math.random().toString(36).substr(2, 9) + '_' + Date.now();

    const token = getAuthToken() || undefined;

    const payloadObj = typeof data === 'object' && data !== null ? { ...data } : { value: data };
    if (token && !payloadObj.token) {
      payloadObj.token = token;
    }

    const frame: WsRequestFrame = {
      id: requestId,
      action: reqname,
      payload: payloadObj,
      // Dual legacy compatibility fields
      type: 'request',
      reqname,
      data: payloadObj,
      requestId,
      token,
    };

    return new Promise<T>((resolve, reject) => {
      // Default 15s timeout for server response
      const timer = setTimeout(() => {
        if (this.pendingRequests.has(requestId)) {
          this.pendingRequests.delete(requestId);
          reject(new Error(`WebSocket request timeout for [${reqname}]`));
        }
      }, timeoutMs);

      this.pendingRequests.set(requestId, { resolve, reject, timer, frame });

      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        try {
          this.ws.send(JSON.stringify(frame));
        } catch (err) {
          clearTimeout(timer);
          this.pendingRequests.delete(requestId);
          reject(err);
        }
      } else {
        // Buffer offline request to replay upon reconnect (deduplicated)
        console.log(`[WS] Offline or reconnecting. Buffering request [${reqname}] (${requestId})`);
        const dataStr = JSON.stringify(data);
        const existingIdx = this.offlineBuffer.findIndex(
          (f) => (f.action === reqname || f.reqname === reqname) && JSON.stringify(f.payload || f.data) === dataStr
        );
        if (existingIdx !== -1) {
          const older = this.offlineBuffer[existingIdx];
          const olderReqId = older.id || older.requestId;
          if (olderReqId && this.pendingRequests.has(olderReqId)) {
            const p = this.pendingRequests.get(olderReqId)!;
            clearTimeout(p.timer);
            this.pendingRequests.delete(olderReqId);
            p.reject(new Error(`Superceded by newer [${reqname}] request`));
          }
          this.offlineBuffer[existingIdx] = frame;
        } else {
          this.offlineBuffer.push(frame);
        }
        this.ensureConnected();
      }
    });
  }

  /**
   * Send un-tracked fire-and-forget payload over WebSocket
   */
  public async send(reqname: string, data: any = {}): Promise<void> {
    const frame: WsRequestFrame = {
      id: 'req_' + Math.random().toString(36).substr(2, 9),
      action: reqname,
      payload: data || {},
      type: 'request',
      reqname,
      data: data || {}
    };

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(frame));
    } else {
      const actionName = reqname || frame.action;
      const dataStr = JSON.stringify(data);
      const existingIdx = this.offlineBuffer.findIndex(
        (f) => (f.action === actionName || f.reqname === actionName) && JSON.stringify(f.payload || f.data) === dataStr
      );
      if (existingIdx !== -1) {
        this.offlineBuffer[existingIdx] = frame;
      } else {
        this.offlineBuffer.push(frame);
      }
      this.ensureConnected();
    }
  }

  /**
   * Subscribe to server push events (e.g. location broadcasts, itinerary updates)
   */
  public on(event: string, callback: EventListener): () => void {
    if (!this.eventListeners.has(event)) {
      this.eventListeners.set(event, new Set());
    }
    this.eventListeners.get(event)!.add(callback);

    return () => {
      this.eventListeners.get(event)?.delete(callback);
    };
  }
}

export const wsClient = new WebSocketClient();
