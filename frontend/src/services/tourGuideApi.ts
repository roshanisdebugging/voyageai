/**
 * VoyageAI — Tour Guide API Service
 * Handles communication over persistent WebSocket (wsClient).
 */

import { wsClient } from './wsClient';
import { getApiBaseUrl, DEFAULT_FETCH_OPTIONS, getAuthHeaders } from '../config/apiConfig';

export interface TourPlace {
  id: string;
  name: string;
  category: string;
  latitude: number;
  longitude: number;
  distanceMeters: number;
  description?: string;
  address?: string;
  openingHours?: string;
  wikipedia?: string;
  source: string;
  dataReliability: 'VERIFIED' | 'ESTIMATED' | 'AI_INTERPRETATION';
  is_mock?: boolean;
  _isMock?: boolean;
}

export interface TourGuideMessage {
  id: string;
  role: 'user' | 'guide';
  text: string;
  timestamp: number;
  placeId?: string;
  places?: TourPlace[];
}

export interface NearbyResponse {
  places: TourPlace[];
  center: { latitude: number; longitude: number };
  radius_m: number;
  count: number;
  total_raw: number;
  proactive_alert: TourPlace | null;
}

export type GuideMode = 'local' | 'trip';

export interface ChatResponse {
  reply: string;
  suggestedActions: string[];
  place: TourPlace | null;
  mode?: GuideMode;
  trip_id?: string | null;
  source: string;
}

export async function fetchNearbyPlaces(
  lat: number,
  lng: number,
  radius: number = 5000
): Promise<NearbyResponse> {
  try {
    const baseUrl = getApiBaseUrl();
    const res = await fetch(`${baseUrl}/api/tour-guide/nearby?lat=${lat}&lng=${lng}&radius=${Math.min(radius, 5000)}`, {
      ...DEFAULT_FETCH_OPTIONS,
      headers: getAuthHeaders(),
    });
    if (res.ok) {
      const data = await res.json();
      return {
        places: data.places || [],
        center: data.center || { latitude: lat, longitude: lng },
        radius_m: data.radius_m || radius,
        count: data.count || (data.places ? data.places.length : 0),
        total_raw: data.total_raw || 0,
        proactive_alert: data.proactive_alert || null
      };
    }
  } catch (err) {
    console.warn('[FETCH NEARBY HTTP WARN]', err);
  }

  try {
    const data = await wsClient.sendRequest('tour_guide:get_nearby', {
      lat,
      lng,
      radius: Math.min(radius, 5000)
    });

    return {
      places: data.places || [],
      center: data.user_location || { latitude: lat, longitude: lng },
      radius_m: data.radius_meters || radius,
      count: data.total || (data.places ? data.places.length : 0),
      total_raw: data.total || 0,
      proactive_alert: data.proactive_alert || null
    };
  } catch (err) {
    console.warn('[FETCH NEARBY WS WARN]', err);
    return {
      places: [],
      center: { latitude: lat, longitude: lng },
      radius_m: radius,
      count: 0,
      total_raw: 0,
      proactive_alert: null
    };
  }
}

export async function sendTourGuideMessage(
  message: string,
  placeId?: string,
  lat?: number,
  lng?: number,
  mode: GuideMode = 'local',
  tripId?: string | null
): Promise<ChatResponse> {
  const payload: Record<string, unknown> = { message, mode };
  if (placeId) payload.place_id = placeId;
  if (tripId) payload.trip_id = tripId;
  if (lat !== undefined) payload.latitude = lat;
  if (lng !== undefined) payload.longitude = lng;

  const data = await wsClient.sendRequest('tour_guide:chat', payload);

  let rawReply = data.response || data.reply || 'No response received.';
  if (typeof rawReply === 'object' && rawReply !== null) {
    rawReply = rawReply.reply || rawReply.text || JSON.stringify(rawReply);
  }

  // Parse raw JSON string if returned like {"reply": "..."}
  let finalReply = String(rawReply).trim();
  if (finalReply.startsWith('{') && finalReply.endsWith('}')) {
    try {
      const parsed = JSON.parse(finalReply);
      if (parsed && typeof parsed === 'object') {
        finalReply = parsed.reply || parsed.text || finalReply;
      }
    } catch { /* proceed */ }
  }

  return {
    reply: finalReply,
    suggestedActions: data.suggestedActions || ['Tell me more', 'What else is nearby?'],
    place: data.active_place || null,
    mode: data.mode || mode,
    trip_id: data.trip_context ? data.trip_context.id : tripId,
    source: 'websocket'
  };
}

export async function setCurrentVisit(placeId: string): Promise<void> {
  await wsClient.sendRequest('tour_guide:visit', { place_id: placeId });
}

// Category display config
export const CATEGORY_CONFIG: Record<string, { label: string; color: string }> = {
  historic: { label: 'Historic', color: '#F59E0B' },
  monument: { label: 'Monument', color: '#F59E0B' },
  fort: { label: 'Fort', color: '#EF4444' },
  palace: { label: 'Palace', color: '#A855F7' },
  museum: { label: 'Museum', color: '#3B82F6' },
  religious: { label: 'Religious', color: '#F97316' },
  temple: { label: 'Temple', color: '#F97316' },
  mosque: { label: 'Mosque', color: '#10B981' },
  church: { label: 'Church', color: '#8B5CF6' },
  cultural: { label: 'Cultural', color: '#EC4899' },
  viewpoint: { label: 'Viewpoint', color: '#14B8A6' },
  park: { label: 'Park', color: '#22C55E' },
  market: { label: 'Market', color: '#F59E0B' },
  ruins: { label: 'Ruins', color: '#78716C' },
  archaeological: { label: 'Archaeological', color: '#92400E' },
  tourism: { label: 'Attraction', color: '#14B8A6' },
  food_landmark: { label: 'Food Landmark', color: '#EF4444' },
};

export function getCategoryDisplay(cat: string) {
  return CATEGORY_CONFIG[cat] || CATEGORY_CONFIG.tourism;
}

export function formatDistance(meters: number): string {
  if (meters < 1000) return `${meters}m`;
  return `${(meters / 1000).toFixed(1)}km`;
}

export const registerUser = async (data: { name: string; email: string; password: string }) => {
  const res = await fetch(`${getApiBaseUrl()}/api/auth/register`, {
    method: 'POST',
    credentials: 'include', // CRITICAL: Allows browser to receive and store HttpOnly cookie
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(data),
  });

  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || 'Registration failed');
  }

  return res.json();
};
