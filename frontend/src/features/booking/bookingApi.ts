/**
 * Booking stage 2 (questions only; nothing is saved to the database or sent to anyone).
 * WS booking:* first, the REST routes as a fallback. Both are owner-only on the server, and voice uses the same state.
 */
import { wsClient } from '../../services/wsClient';
import { fetchWithAuth, getApiBaseUrl } from '../../config/apiConfig';

export interface BookingChoice { value: string; label: string }
export interface BookingSummaryLine { part: string; label: string; text: string; note?: string }
export type BookingKind = 'services' | 'choice' | 'name' | 'age' | 'phone' | 'yesno' | 'review' | 'change';

export interface BookingCard { rows: { key: string; label: string; value: string; current: boolean }[]; now: string }

/** A saved booking request (stage 3): number and status only, for its owner. */
export interface BookingRequestInfo {
  requestNo: string; status: string; statusLabel: string; open: boolean; createdAt?: string | null;
  /** Stage 4, the partner email: off (not emailed) / sending / sent / failed, and the line to show for it. */
  notify?: 'off' | 'sending' | 'sent' | 'failed';
  notifyText?: string;
}

export interface TravelDetails {
  travelers: { name: string | null; age: number | null; isChild: boolean }[];
  phone: string | null;
}

export interface TravelDetailsAnswer {
  travellers: { name: string; age: string }[];
  phone: string;
  confirmAgeMismatch: boolean;
}

export interface BookingView {
  active: boolean;
  tripId?: string;
  question?: string;
  kind?: BookingKind;
  prompt?: string;
  choices?: BookingChoice[];
  allowText?: boolean;
  selected?: string[];
  progress?: { step: number; total: number; label: string };
  canBack?: boolean;
  testNote?: string;
  error?: string | null;
  errorCode?: string | null;
  traveller?: { index: number; isChild: boolean; total: number };
  summary?: BookingSummaryLine[];
  consent?: string;
  /** Traveller 1 only: the account's name for the optional "Mera naam" button (never filled in by itself). */
  accountName?: string;
  partnerNotes?: string[];
  /** The live summary: every field of the chosen services, "-" until answered, the current one marked. */
  card?: BookingCard;
  /** The owner's latest saved request for this trip (null when none). */
  request?: BookingRequestInfo | null;
  finished?: boolean;
  cancelled?: boolean;
  expired?: boolean;
  message?: string;
  offer?: string;
  travelDetails?: TravelDetails;
  currentAnswer?: string | number | null;
}

async function call(action: string, tripId: string, payload: Record<string, unknown>,
                    method: 'GET' | 'POST' | 'DELETE', path: string): Promise<BookingView> {
  try {
    return await wsClient.sendRequest<BookingView>(action, { ...payload, trip_id: tripId });
  } catch {
    const res = await fetchWithAuth(`${getApiBaseUrl()}/api/trips/${encodeURIComponent(tripId)}/booking${path}`, {
      method,
      headers: method === 'POST' ? { 'Content-Type': 'application/json' } : undefined,
      body: method === 'POST' ? JSON.stringify(payload) : undefined,
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = body?.detail;
      throw new Error(typeof detail?.message === 'string' ? detail.message
        : typeof detail === 'string' ? detail : "Booking couldn't load. Please try again.");
    }
    return body as BookingView;
  }
}

export const bookingApi = {
  get: (tripId: string) => call('booking:get', tripId, {}, 'GET', ''),
  start: (tripId: string, services?: string[]) =>
    call('booking:start', tripId, services?.length ? { services } : {}, 'POST', '/start'),
  answer: (tripId: string, question: string, value: string | string[] | TravelDetailsAnswer) =>
    call('booking:answer', tripId, { question, value }, 'POST', '/answer'),
  request: (tripId: string) => call('booking:request', tripId, {}, 'GET', '/request'),
  back: (tripId: string) => call('booking:back', tripId, {}, 'POST', '/back'),
  cancel: (tripId: string) => call('booking:cancel', tripId, {}, 'DELETE', ''),
};
