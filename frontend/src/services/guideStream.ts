/**
 * Jarvis streamed chat over Server-Sent Events (POST /api/tour-guide/chat/stream).
 * Kept free of app imports (the fetch call is passed in) so `npm test` can run it in plain node.
 * Server events: start {provider} -> token {t}* -> done {reply, chips, card, mode, gate, grounded, provider, error},
 * or error {code, message, partial?, chips?}.
 */
import { createSseParser } from './sseParser';

/** A real place from Google (Jarvis "nearest hospital" etc.). Unknown values are null, never guessed.
 *  phone and address are only in the live reply; the saved history leaves them out. */
export interface GuidePlace {
  name: string;
  lat: number;
  lng: number;
  distance_m: number | null;
  rating: number | null;
  rating_count?: number | null;
  open_now: boolean | null;
  phone?: string | null;
  address?: string | null;
  maps_url?: string | null;
}

export interface GuideStreamDone {
  reply: string;
  chips: string[];
  card: Record<string, unknown> | null;
  mode?: 'local' | 'trip';
  gate?: string;
  grounded: boolean;
  provider: 'openai' | 'gemini' | null;
  error: string | null;
  places: GuidePlace[];
  emergency: boolean;
  needs_location: boolean;
}

/** Only well-formed places (name + coordinates); everything else in a place is optional. */
export function cleanGuidePlaces(raw: unknown): GuidePlace[] {
  if (!Array.isArray(raw)) return [];
  const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  const str = (v: unknown) => (typeof v === 'string' && v.trim() ? v : null);
  return raw
    .filter((p: any) => p && typeof p.name === 'string' && p.name.trim() && num(p.lat) !== null && num(p.lng) !== null)
    .slice(0, 5)
    .map((p: any) => ({
      name: p.name,
      lat: p.lat,
      lng: p.lng,
      distance_m: num(p.distance_m),
      rating: num(p.rating),
      rating_count: num(p.rating_count),
      open_now: typeof p.open_now === 'boolean' ? p.open_now : null,
      phone: str(p.phone),
      address: str(p.address),
      // Only Google Maps links (the server sends googleMapsUri); anything else is dropped.
      maps_url: str(p.maps_url) && /^https:\/\/(maps\.google\.com|www\.google\.com\/maps|maps\.app\.goo\.gl)\//.test(p.maps_url)
        ? p.maps_url : null,
    }));
}

export interface GuideStreamError {
  code: string;
  message: string;
  partial?: boolean;
  chips?: string[];
}

export interface GuideStreamHandlers {
  onStart?: (info: { provider: string | null }) => void;
  onToken?: (text: string) => void;
  onDone?: (data: GuideStreamDone) => void;
  onError?: (err: GuideStreamError) => void;
  signal?: AbortSignal;
}

/**
 * The stream couldn't deliver an answer.
 * `unreachable`: endpoint missing (404/405) or a network error before any response, so nothing was shown and
 *   the caller may fall back once to POST /api/tour-guide/chat. Other HTTP errors (401, 429, 5xx) are not
 *   unreachable: a second paid call wouldn't help.
 * `broken`: the connection ended mid-way, without `done` or `error`.
 */
export class GuideStreamFailure extends Error {
  unreachable: boolean;
  broken: boolean;
  status?: number;

  constructor(message: string, opts: { unreachable?: boolean; broken?: boolean; status?: number } = {}) {
    super(message);
    this.name = 'GuideStreamFailure';
    this.unreachable = !!opts.unreachable;
    this.broken = !!opts.broken;
    this.status = opts.status;
  }
}

const isAbort = (err: unknown, signal?: AbortSignal) =>
  (err as Error)?.name === 'AbortError' || !!signal?.aborted;

/**
 * POSTs `body` through `doFetch` and reads the event stream. Resolves 'done' or 'error' after calling onDone /
 * onError; rejects with GuideStreamFailure, or with the AbortError when `signal` aborts.
 */
export async function runGuideStream(
  doFetch: (init: RequestInit) => Promise<Response>,
  body: Record<string, unknown>,
  handlers: GuideStreamHandlers = {},
): Promise<'done' | 'error'> {
  const { onStart, onToken, onDone, onError, signal } = handlers;
  let res: Response;
  try {
    res = await doFetch({
      method: 'POST',
      headers: { Accept: 'text/event-stream' },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (isAbort(err, signal)) throw err;
    throw new GuideStreamFailure('Stream endpoint unreachable', { unreachable: true });
  }
  if (!res.ok || !res.body) {
    throw new GuideStreamFailure(`Stream HTTP ${res.status}`, {
      unreachable: res.status === 404 || res.status === 405 || (res.ok && !res.body),
      status: res.status,
    });
  }

  let outcome: 'done' | 'error' | null = null;
  const parser = createSseParser(({ event, data }) => {
    if (outcome) return;
    let parsed: any;
    try {
      parsed = JSON.parse(data);
    } catch {
      return;
    }
    if (event === 'start') {
      onStart?.({ provider: parsed?.provider ?? null });
    } else if (event === 'token' && typeof parsed?.t === 'string') {
      onToken?.(parsed.t);
    } else if (event === 'done') {
      outcome = 'done';
      onDone?.({
        reply: String(parsed?.reply ?? ''),
        chips: Array.isArray(parsed?.chips) ? parsed.chips.filter((c: unknown) => typeof c === 'string') : [],
        card: parsed?.card && typeof parsed.card === 'object' ? parsed.card : null,
        mode: parsed?.mode,
        gate: parsed?.gate,
        grounded: parsed?.grounded === true,
        provider: parsed?.provider ?? null,
        error: parsed?.error ?? null,
        places: cleanGuidePlaces(parsed?.places),
        emergency: parsed?.emergency === true,
        needs_location: parsed?.needs_location === true,
      });
    } else if (event === 'error') {
      outcome = 'error';
      onError?.({
        code: String(parsed?.code ?? 'STREAM_ERROR'),
        message: String(parsed?.message ?? ''),
        partial: parsed?.partial === true,
        chips: Array.isArray(parsed?.chips) ? parsed.chips : undefined,
      });
    }
  });

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      parser.feed(decoder.decode(value, { stream: true }));
      if (outcome) break;
    }
    if (!outcome) {
      parser.feed(decoder.decode());
      parser.end();
    }
  } catch (err) {
    if (isAbort(err, signal)) throw err;
    if (!outcome) throw new GuideStreamFailure('Stream broke', { broken: true });
  } finally {
    if (outcome) reader.cancel().catch(() => undefined);
  }
  if (!outcome) throw new GuideStreamFailure('Stream ended without an answer', { broken: true });
  return outcome;
}
