/**
 * VoyageAI — Unified Location Service Abstraction
 * Web-first implementation wrapping HTML5 Geolocation API.
 * Abstracts location provider logic so that future mobile (React Native / iOS / Android)
 * location APIs can be swapped without changing UI context.
 */

export interface NormalizedLocationPoint {
  latitude: number;
  longitude: number;
  accuracy: number;
  heading: number | null;
  speed: number | null;
  timestamp: number;
  source: 'gps' | 'manual';
  addressName?: string;
}

export interface LocationWatcherConfig {
  distanceThresholdMeters: number; // Minimum movement (default 10m)
  timeThresholdMs: number;         // Minimum interval between backend syncs (default 5000ms)
  enableHighAccuracy: boolean;
  timeoutMs: number;
  maximumAgeMs: number;
}

const DEFAULT_CONFIG: LocationWatcherConfig = {
  distanceThresholdMeters: 10,
  timeThresholdMs: 5000,
  enableHighAccuracy: false,
  timeoutMs: 15000,
  maximumAgeMs: 10000
};

import { getApiBaseUrl, DEFAULT_HEADERS } from '../config/apiConfig';

/**
 * Reverse-geocode latitude and longitude into an accurate city/town name via Google Geocoding API proxy.
 * Uses backend /api/location/reverse.
 */
export async function reverseGeocodeCoords(lat: number, lng: number): Promise<string> {
  try {
    const baseUrl = getApiBaseUrl();
    const res = await fetch(`${baseUrl}/api/location/reverse?lat=${lat}&lng=${lng}`, {
      headers: DEFAULT_HEADERS,
    });
    if (res.ok) {
      const data = await res.json();
      const city = data.city || data.state;
      if (city && city.trim().length > 0 && city !== 'Current Location') return city.trim();
      if (data.formatted_address) {
        const parts = data.formatted_address.split(',');
        if (parts.length > 0) return parts[0].trim();
      }
    }
  } catch (e) {
    console.warn('[GEOCODE] Reverse geocode failed:', e);
  }
  return 'Current Location';
}

// Haversine distance calculator in meters
export function haversineMeters(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371000;
  const dlat = ((lat2 - lat1) * Math.PI) / 180;
  const dlon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dlat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dlon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

class LocationService {
  private watchId: number | null = null;
  private isTracking = false;
  private isManualOverride = false;
  private lastNormalizedPoint: NormalizedLocationPoint | null = null;
  private lastSyncedPoint: NormalizedLocationPoint | null = null;
  private config: LocationWatcherConfig = DEFAULT_CONFIG;
  private onUpdateCallback: ((point: NormalizedLocationPoint, shouldSyncBackend: boolean) => void) | null = null;
  private onErrorCallback: ((err: GeolocationPositionError) => void) | null = null;

  /**
   * Single owner of the geolocation watcher.
   */
  public startWatcher(
    onLocationUpdate: (point: NormalizedLocationPoint, shouldSyncBackend: boolean) => void,
    onError?: (err: GeolocationPositionError) => void,
    customConfig?: Partial<LocationWatcherConfig>
  ): boolean {
    this.onUpdateCallback = onLocationUpdate;
    if (onError) this.onErrorCallback = onError;

    if (this.watchId !== null) {
      console.log('[LOCATION SERVICE] Watcher already running.');
      return true;
    }

    if (!('geolocation' in navigator)) {
      console.warn('[LOCATION SERVICE] Geolocation API unavailable in browser');
      return false;
    }

    this.config = { ...DEFAULT_CONFIG, ...customConfig };
    this.isTracking = true;

    console.log('[LOCATION SERVICE] ▶️ Starting unified geolocation watcher...');

    this.watchId = navigator.geolocation.watchPosition(
      (pos) => {
        // If user manually overrode location, suppress automatic GPS updates
        if (this.isManualOverride) {
          console.log('[LOCATION SERVICE] Manual location override active. Suppressing GPS callback.');
          return;
        }

        const now = pos.timestamp || Date.now();
        const point: NormalizedLocationPoint = {
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          accuracy: pos.coords.accuracy,
          heading: pos.coords.heading,
          speed: pos.coords.speed,
          timestamp: now,
          source: 'gps'
        };

        // Filter out extreme invalid GPS noise (e.g. accuracy > 5000m)
        if (point.accuracy > 5000) {
          console.warn(`[LOCATION SERVICE] Discarding extreme GPS outlier (accuracy: ${point.accuracy}m)`);
          return;
        }

        this.lastNormalizedPoint = point;

        // Evaluate throttling: should sync to backend via WebSocket/HTTP?
        let shouldSync = false;
        if (!this.lastSyncedPoint) {
          shouldSync = true;
        } else {
          const dist = haversineMeters(
            this.lastSyncedPoint.latitude,
            this.lastSyncedPoint.longitude,
            point.latitude,
            point.longitude
          );
          const timeDelta = now - this.lastSyncedPoint.timestamp;

          if (dist >= this.config.distanceThresholdMeters || timeDelta >= this.config.timeThresholdMs) {
            shouldSync = true;
          }
        }

        if (shouldSync) {
          this.lastSyncedPoint = point;
        }

        if (this.onUpdateCallback) {
          this.onUpdateCallback(point, shouldSync);
        }
      },
      (err) => {
        console.warn('[LOCATION SERVICE] Watcher error:', err.message);
        if (this.onErrorCallback) {
          this.onErrorCallback(err);
        }
      },
      {
        enableHighAccuracy: this.config.enableHighAccuracy,
        timeout: this.config.timeoutMs,
        maximumAge: this.config.maximumAgeMs
      }
    );

    return true;
  }

  public stopWatcher(): void {
    if (this.watchId !== null && 'geolocation' in navigator) {
      console.log('[LOCATION SERVICE] ⏹️ Stopping geolocation watcher.');
      navigator.geolocation.clearWatch(this.watchId);
      this.watchId = null;
    }
    this.isTracking = false;
  }

  public setManualOverride(point: NormalizedLocationPoint): void {
    this.isManualOverride = true;
    this.lastNormalizedPoint = point;
    this.lastSyncedPoint = point;
  }

  public clearManualOverride(): void {
    this.isManualOverride = false;
  }

  public getIsManualOverride(): boolean {
    return this.isManualOverride;
  }

  public getIsTracking(): boolean {
    return this.isTracking;
  }

  public getLastPoint(): NormalizedLocationPoint | null {
    return this.lastNormalizedPoint;
  }
}

export const locationService = new LocationService();
