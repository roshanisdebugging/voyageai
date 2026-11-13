/**
 * VoyageAI — Real-Time WebSocket Location Client
 * Connects to ws://127.0.0.1:8000/ws/location for streaming user GPS coordinates.
 * Handles automatic reconnection with exponential backoff and trip subscription broadcasting.
 */

import { getWsBaseUrl } from '../config/apiConfig';

export interface LocationSocketPayload {
  type: 'location_update';
  latitude: number;
  longitude: number;
  accuracy_meters?: number;
  heading?: number | null;
  speed?: number | null;
  source?: 'gps' | 'manual';
  address_name?: string;
  trip_id?: string | null;
}

export interface LocationAck {
  type: 'location_ack';
  status: string;
  timestamp: string;
  distance_delta_m?: number | null;
}

export interface LocationBroadcast {
  type: 'location_broadcast';
  user_id: string;
  trip_id: string;
  location: {
    latitude: number;
    longitude: number;
    accuracy_meters?: number;
    address_name?: string;
    timestamp: string;
  };
}

class LocationSocketClient {
  private ws: WebSocket | null = null;
  private isConnecting = false;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  public getIsConnecting(): boolean {
    return this.isConnecting;
  }
  private currentTripId: string | null = null;
  private ackListeners: Set<(ack: LocationAck) => void> = new Set();
  private broadcastListeners: Set<(broadcast: LocationBroadcast) => void> = new Set();
  private lastPayload: LocationSocketPayload | null = null;

  public setActiveTripId(tripId: string | null): void {
    this.currentTripId = tripId || null;
  }

  public connect(tripId?: string | null): void {
    if (tripId !== undefined) {
      this.currentTripId = tripId || null;
    }

    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    this.isConnecting = true;
    let url = getWsBaseUrl('/ws/location');

    if (this.currentTripId) {
      const sep = url.includes('?') ? '&' : '?';
      url = `${url}${sep}trip_id=${encodeURIComponent(this.currentTripId)}`;
    }

    console.log(`[LOCATION SOCKET] Connecting to ${url}...`);

    try {
      this.ws = new WebSocket(url);

      this.ws.onopen = () => {
        console.log('[LOCATION SOCKET] Connected successfully!');
        this.isConnecting = false;
        this.reconnectAttempts = 0;

        // Flush last unsent payload if reconnecting
        if (this.lastPayload) {
          this.sendLocation(this.lastPayload);
        }
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'location_ack') {
            this.ackListeners.forEach(cb => cb(data));
          } else if (data.type === 'location_broadcast') {
            this.broadcastListeners.forEach(cb => cb(data));
          }
        } catch (err) {
          console.warn('[LOCATION SOCKET] Message parse error:', err);
        }
      };

      this.ws.onerror = (err) => {
        console.warn('[LOCATION SOCKET] Error:', err);
      };

      this.ws.onclose = (event) => {
        console.log(`[LOCATION SOCKET] Closed (code: ${event.code})`);
        this.ws = null;
        this.isConnecting = false;

        // Don't reconnect if closed cleanly by client (e.g. 1000) or rejected auth (4003)
        if (event.code !== 1000 && event.code !== 4003 && this.reconnectAttempts < this.maxReconnectAttempts) {
          this.scheduleReconnect();
        }
      };
    } catch (err) {
      console.warn('[LOCATION SOCKET] Connection exception:', err);
      this.isConnecting = false;
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts - 1), 10000);
    console.log(`[LOCATION SOCKET] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})...`);
    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, delay);
  }

  public sendLocation(payload: LocationSocketPayload): boolean {
    const finalPayload = {
      ...payload,
      lat: payload.latitude,
      lng: payload.longitude,
      accuracy: payload.accuracy_meters !== undefined ? payload.accuracy_meters : 10,
      trip_id: this.currentTripId || payload.trip_id || null
    };

    this.lastPayload = payload;

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      try {
        this.ws.send(JSON.stringify(finalPayload));
        return true;
      } catch (err) {
        console.warn('[LOCATION SOCKET] Send error:', err);
        return false;
      }
    } else {
      // Connect if disconnected
      this.connect();
      return false;
    }
  }

  public sendPosition(coords: { latitude: number; longitude: number; accuracy?: number }): boolean {
    return this.sendLocation({
      type: 'location_update',
      latitude: coords.latitude,
      longitude: coords.longitude,
      accuracy_meters: coords.accuracy,
      source: 'gps',
      trip_id: this.currentTripId || null
    });
  }

  public disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close(1000, 'Client disconnect');
      this.ws = null;
    }
    this.reconnectAttempts = 0;
  }

  public onAck(callback: (ack: LocationAck) => void): () => void {
    this.ackListeners.add(callback);
    return () => this.ackListeners.delete(callback);
  }

  public onBroadcast(callback: (broadcast: LocationBroadcast) => void): () => void {
    this.broadcastListeners.add(callback);
    return () => this.broadcastListeners.delete(callback);
  }

  public isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }
}

export const locationSocket = new LocationSocketClient();
