// Jarvis streamed chat: the SSE parser (src/services/sseParser.ts) and streamTourGuideMessage
// (runGuideStream in src/services/guideStream.ts) against a fake fetch. Run from frontend/: npm test
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadTs } from './tsload.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const P = await loadTs(join(here, '..', 'src', 'services', 'sseParser.ts'));

let failed = 0, total = 0;
const check = (name, ok, detail = '') => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail !== '' ? `  [${detail}]` : ''}`); };

const STREAM = 'event: start\ndata: {"provider": "openai"}\n\n'
  + ': keepalive\n\n'
  + 'event: token\ndata: {"t": "Hawa Mahal "}\n\n'
  + 'event: token\r\ndata: {"t": "dekhiye."}\r\n\r\n'
  + 'event: done\ndata: {"reply": "Hawa Mahal dekhiye.", "chips": ["Timings"], "card": null, "grounded": false, "provider": "openai", "error": null}\n\n';

function parseAll(chunks) {
  const out = [];
  const p = P.createSseParser((e) => out.push(e));
  for (const c of chunks) p.feed(c);
  p.end();
  return out;
}

const whole = parseAll([STREAM]);
check('parser: 4 events (comment skipped)', whole.length === 4, whole.map((e) => e.event).join(','));
check('parser: names in order', whole.map((e) => e.event).join(',') === 'start,token,token,done');
check('parser: CRLF lines handled', JSON.parse(whole[2].data).t === 'dekhiye.', whole[2].data);

let sameEverywhere = true;
for (let size = 1; size <= 7; size++) {
  const chunks = [];
  for (let i = 0; i < STREAM.length; i += size) chunks.push(STREAM.slice(i, i + size));
  const got = parseAll(chunks);
  if (JSON.stringify(got) !== JSON.stringify(whole)) sameEverywhere = false;
}
check('parser: identical result for chunks of 1..7 chars (events split across reads)', sameEverywhere);
const tail = parseAll(['event: done\ndata: {"reply": "x"}']);
check('parser: last event without a blank line is delivered on end()', tail.length === 1 && tail[0].event === 'done');
const multi = parseAll(['data: a\ndata: b\n\n']);
check('parser: multi-line data joined, default event "message"', multi[0].data === 'a\nb' && multi[0].event === 'message');

// ---- runGuideStream (what streamTourGuideMessage calls with fetchWithAuth) against a fake fetch, no network
const api = await loadTs(join(here, '..', 'src', 'services', 'guideStream.ts'));
const URL_STREAM = 'http://localhost:8000/api/tour-guide/chat/stream';

function bodyOf(chunks, { breakAfter = false } = {}) {
  const enc = new TextEncoder();
  let i = 0;
  return new ReadableStream({
    pull(ctrl) {
      if (i < chunks.length) ctrl.enqueue(enc.encode(chunks[i++]));
      else if (breakAfter) ctrl.error(new TypeError('network'));
      else ctrl.close();
    },
  });
}

if (api) {
  const calls = [];
  const run = async (respond, extra = {}) => {
    const doFetch = async (init) => { calls.push({ url: URL_STREAM, init }); return respond(); };
    const seen = { start: null, tokens: [], done: null, error: null };
    let result, thrown = null;
    try {
      result = await api.runGuideStream(doFetch, { message: 'Hawa Mahal' }, {
        onStart: (s) => { seen.start = s; },
        onToken: (t) => seen.tokens.push(t),
        onDone: (d) => { seen.done = d; },
        onError: (e) => { seen.error = e; },
        ...extra,
      });
    } catch (e) { thrown = e; }
    return { seen, result, thrown };
  };

  const chunks = [];
  for (let i = 0; i < STREAM.length; i += 9) chunks.push(STREAM.slice(i, i + 9));
  let r = await run(() => new Response(bodyOf(chunks), { status: 200, headers: { 'content-type': 'text/event-stream' } }));
  check('stream: POSTs the JSON body, asks for text/event-stream', calls[0].init.method === 'POST'
    && JSON.parse(calls[0].init.body).message === 'Hawa Mahal' && calls[0].init.headers.Accept === 'text/event-stream');
  check('stream: onStart -> tokens -> onDone, resolves "done"', r.result === 'done' && r.seen.start?.provider === 'openai'
    && r.seen.tokens.join('') === 'Hawa Mahal dekhiye.' && r.seen.done?.reply === 'Hawa Mahal dekhiye.', JSON.stringify(r.seen));
  check('stream: done carries chips, provider, grounded', JSON.stringify(r.seen.done.chips) === '["Timings"]'
    && r.seen.done.provider === 'openai' && r.seen.done.grounded === false);

  r = await run(() => new Response(bodyOf(['event: start\ndata: {"provider":"openai"}\n\n', 'event: token\ndata: {"t":"Half "}\n\n',
    'event: error\ndata: {"code":"STREAM_INTERRUPTED","message":"cut","partial":true}\n\n']), { status: 200 }));
  check('stream: server error event -> onError(partial), resolves "error"', r.result === 'error' && r.seen.error?.partial === true
    && r.seen.tokens.join('') === 'Half ', JSON.stringify(r.seen));

  r = await run(() => new Response('not found', { status: 404 }));
  check('stream: 404 -> GuideStreamFailure unreachable (caller falls back to the JSON route)',
    r.thrown instanceof api.GuideStreamFailure && r.thrown.unreachable === true, r.thrown?.message);
  r = await run(() => { throw new TypeError('Failed to fetch'); });
  check('stream: network error before a response -> unreachable', r.thrown?.unreachable === true, r.thrown?.message);
  r = await run(() => new Response('{"detail":"busy"}', { status: 429 }));
  check('stream: 429 -> failure, NOT unreachable (no second paid call)', r.thrown instanceof api.GuideStreamFailure
    && r.thrown.unreachable === false && r.thrown.status === 429);

  r = await run(() => new Response(bodyOf(['event: token\ndata: {"t":"Hawa "}\n\n'], { breakAfter: true }), { status: 200 }));
  check('stream: connection drops mid-way -> broken failure after the tokens shown', r.thrown?.broken === true
    && r.seen.tokens.join('') === 'Hawa ', r.thrown?.message);
  r = await run(() => new Response(bodyOf(['event: token\ndata: {"t":"Hawa "}\n\n']), { status: 200 }));
  check('stream: ends without done/error -> broken', r.thrown?.broken === true);

  const ac = new AbortController();
  r = await run(() => { ac.abort(); const e = new Error('aborted'); e.name = 'AbortError'; throw e; }, { signal: ac.signal });
  check('stream: abort -> AbortError passed through (not a fallback)', r.thrown?.name === 'AbortError');
}

// ---- places in `done` (Jarvis "nearest hospital"), and the card helpers
{
  const placesDone = 'event: done\ndata: ' + JSON.stringify({
    reply: 'Emergency ho to 112 ya 108 dial karein. SMS Hospital paas hai.', chips: [], card: null, grounded: false,
    provider: 'openai', error: null, emergency: true, needs_location: false,
    places: [
      { name: 'SMS Hospital', lat: 26.92, lng: 75.79, distance_m: 1300, rating: 4.2, rating_count: 120, open_now: true,
        phone: '0141 251 8222', address: 'JLN Marg', maps_url: 'https://maps.google.com/?cid=2' },
      { name: 'No coords', distance_m: 10 },
      { name: 'Odd link', lat: 26.9, lng: 75.8, distance_m: 2000, rating: null, open_now: null, maps_url: 'https://evil.example/x' },
    ],
  }) + '\n\n';
  const seen = {};
  await api.runGuideStream(async () => new Response(placesDone, { status: 200 }), {}, { onDone: (d) => { seen.done = d; } });
  const d = seen.done;
  check('done: places parsed, the one without coordinates dropped', d.places.length === 2 && d.places[0].name === 'SMS Hospital',
    JSON.stringify(d.places));
  check('done: emergency + needs_location flags', d.emergency === true && d.needs_location === false);
  check('done: phone, open_now, rating kept; unknowns stay null', d.places[0].phone === '0141 251 8222' && d.places[0].open_now === true
    && d.places[1].open_now === null && d.places[1].rating === null);
  check('done: only Google Maps links kept', d.places[0].maps_url === 'https://maps.google.com/?cid=2' && d.places[1].maps_url === null);
  const old = 'event: done\ndata: {"reply": "x", "chips": []}\n\n';
  await api.runGuideStream(async () => new Response(old, { status: 200 }), {}, { onDone: (x) => { seen.old = x; } });
  check('done without place fields (old server) -> [] and false', Array.isArray(seen.old.places) && seen.old.places.length === 0
    && seen.old.emergency === false && seen.old.needs_location === false);
  check('cleanGuidePlaces: not an array -> []', api.cleanGuidePlaces(null).length === 0 && api.cleanGuidePlaces('x').length === 0);
  check('cleanGuidePlaces: at most 5',
    api.cleanGuidePlaces(Array.from({ length: 9 }, (_, i) => ({ name: `P${i}`, lat: 1, lng: 2 }))).length === 5);

  const H = await loadTs(join(here, '..', 'src', 'components', 'tour-guide', 'guidePlaces.ts'));
  check('distance label: 450 m / 1.3 km / unknown hidden', H.placeDistanceLabel(450) === '450 m'
    && H.placeDistanceLabel(1300) === '1.3 km' && H.placeDistanceLabel(null) === null);
  check('directions: Google link when sent, else Google Maps directions to the pin',
    H.directionsUrl({ lat: 1, lng: 2, maps_url: 'https://maps.google.com/?cid=2' }) === 'https://maps.google.com/?cid=2'
    && H.directionsUrl({ lat: 26.9, lng: 75.8, maps_url: null }) === 'https://www.google.com/maps/dir/?api=1&destination=26.9,75.8');
  check('tel link keeps digits and +', H.telHref('+91 141-251 8222') === 'tel:+911412518222');
}

console.log(`\n${total - failed}/${total} passed`);
if (failed) process.exit(1);
