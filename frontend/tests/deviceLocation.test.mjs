// Travel-time origin = the device's current location, always (src/services/deviceLocation*.ts). Run from frontend/: npm test
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { loadTs } from './tsload.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'src');
const L = await loadTs(join(src, 'services', 'deviceLocationLogic.ts'));
const S = await loadTs(join(src, 'services', 'deviceLocation.ts'));

let failed = 0, total = 0;
const check = (name, ok, detail = '') => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail !== '' ? `  [${detail}]` : ''}`); };

// Jaipur points
const ME = { lat: 26.9124, lng: 75.7873 };          // the device
const HAWA = { latitude: 26.9239, longitude: 75.8267 };
const AMER = { lat: 26.9855, lng: 75.8513 };
const MUMBAI = { latitude: 19.0760, longitude: 72.8777 };
const north = (p, m) => ({ ...p, lat: p.lat + m / 111_320 });   // move m metres north

function fakeWorld() {
  const w = { fix: null, err: null, calls: [], logs: [], queue: [], t: 1_000_000, inFlight: 0, maxInFlight: 0 };
  w.geo = { getCurrentPosition: (ok, fail) => (w.err ? fail(w.err) : ok({ coords: { latitude: w.fix.lat, longitude: w.fix.lng, accuracy: w.fix.acc } })) };
  w.compute = async (o, d, mode) => {
    w.calls.push({ o, d, mode });
    w.inFlight++; w.maxInFlight = Math.max(w.maxInFlight, w.inFlight);
    await new Promise((r) => setTimeout(r, 5));
    w.inFlight--;
    const next = w.queue.shift();
    if (next) throw next;
    return { distance_m: 6800, duration_s: 1380, polyline: null, mode, warning: null };
  };
  w.store = S.createDeviceLocationStore({ geo: w.geo, compute: w.compute, now: () => w.t, log: (l) => w.logs.push(l) });
  return w;
}

// ---- no location / errors: never a Google call
{
  const w = fakeWorld();
  check('before any reading: no-location', L.travelPlan(w.store.getState(), HAWA).kind === 'no-location');
  w.err = { code: 1 };
  await w.store.read();
  const p = L.travelPlan(w.store.getState(), HAWA);
  check('permission denied -> no-location (denied)', p.kind === 'no-location' && p.reason === 'denied', JSON.stringify(p));
  check('denied -> says why', L.noLocationReason('denied').startsWith('Location access is blocked'));
  w.err = { code: 3 }; await w.store.read();
  check('timeout -> error timeout', w.store.getState().error === 'timeout');
  w.err = { code: 2 }; await w.store.read();
  check('unavailable -> error unavailable', w.store.getState().error === 'unavailable');
  const none = S.createDeviceLocationStore({ geo: null, compute: w.compute, log: () => {} });
  await none.read();
  check('no geolocation in the browser -> unsupported', none.getState().error === 'unsupported');
  await w.store.route({ lat: 1, lng: 1 }, 'drive', 'itinerary').then(() => check('route without origin rejected', false), () => check('route without origin rejected', true));
  check('no location -> zero Google calls', w.calls.length === 0);
}

// ---- poor accuracy (worse than 1 km): straight-line only
{
  const w = fakeWorld();
  w.fix = { ...ME, acc: 1500 };
  await w.store.read();
  const p = L.travelPlan(w.store.getState(), HAWA);
  check('accuracy 1.5 km -> poor, straight-line distance kept', p.kind === 'poor' && p.straightM > 3000 && p.straightM < 5000, JSON.stringify(p));
  check('poor -> "We couldn’t determine your precise location"', L.noLocationReason('poor') === 'We couldn’t determine your precise location.');
  check('poor -> no route origin', w.store.getState().origin === null);
  w.fix = { ...ME, acc: 1000 };
  await w.store.read();
  check('accuracy exactly 1 km -> usable', L.travelPlan(w.store.getState(), HAWA).kind === 'route');
}

// ---- the origin is the device location; near / far rules
{
  const w = fakeWorld();
  w.fix = { ...ME, acc: 30 };
  await w.store.read();
  const st = w.store.getState();
  check('reading has {lat, lng, accuracy_m, updatedAt}', st.reading.lat === ME.lat && st.reading.accuracy_m === 30 && st.reading.updatedAt === w.t);
  check('label "From: Your location (accuracy 30 m)"', L.originLabel(30) === 'From: Your location (accuracy 30 m)');
  const p = L.travelPlan(st, HAWA);
  check('Hawa Mahal 4 km away -> route', p.kind === 'route', p.kind);
  await w.store.route({ lat: HAWA.latitude, lng: HAWA.longitude }, 'drive', 'itinerary', true);
  check('Google origin == the device location (not a previous activity / hotel / trip)',
    w.calls.length === 1 && w.calls[0].o.lat === ME.lat && w.calls[0].o.lng === ME.lng, JSON.stringify(w.calls[0]?.o));
  check('over 300 km (Mumbai) -> far, no call', L.travelPlan(st, MUMBAI).kind === 'far' && L.farKm(L.travelPlan(st, MUMBAI).straightM).endsWith(' km'));
  check('under 150 m -> here', L.travelPlan(st, { latitude: ME.lat + 0.0009, longitude: ME.lng }).kind === 'here');
  check('151-ish m -> route', L.travelPlan(st, { latitude: ME.lat + 0.0015, longitude: ME.lng }).kind === 'route');
  check('activity without coordinates -> no line', L.travelPlan(st, { latitude: null, longitude: undefined }).kind === 'no-coords');
  check('Open in Google Maps link has both coordinates',
    L.googleMapsDirectionsUrl(ME, AMER) === 'https://www.google.com/maps/dir/?api=1&origin=26.912400%2C75.787300&destination=26.985500%2C75.851300&travelmode=driving');
}

// ---- moves: 200 m -> no new call; 400 m -> a new call; reopen -> no call
{
  const w = fakeWorld();
  w.fix = { ...ME, acc: 20 };
  await w.store.read();
  const dest = { lat: AMER.lat, lng: AMER.lng };
  await w.store.route(dest, 'drive', 'itinerary', true);
  await w.store.route(dest, 'drive', 'itinerary', true);
  check('same card again (reopen the day) -> no new call', w.calls.length === 1, w.calls.length);
  const m200 = north(ME, 200);
  w.fix = { ...m200, acc: 20 }; w.t += 120_000;
  await w.store.read();
  check('moved 200 m -> origin unchanged', w.store.getState().origin.lat === ME.lat);
  await w.store.route(dest, 'drive', 'itinerary', true);
  check('moved 200 m -> no new Google call', w.calls.length === 1, w.calls.length);
  const m400 = north(ME, 400);
  w.fix = { ...m400, acc: 20 }; w.t += 120_000;
  await w.store.read();
  check('moved 400 m -> origin moves to the new device location', Math.abs(w.store.getState().origin.lat - m400.lat) < 1e-9);
  await w.store.route(dest, 'drive', 'itinerary', true);
  check('moved 400 m -> one new Google call, from the new location', w.calls.length === 2 && Math.abs(w.calls[1].o.lat - m400.lat) < 1e-9, w.calls.length);
  await w.store.route(dest, 'walk', 'map');
  check('another mode is its own call', w.calls.length === 3);
  check('ensureFresh within a minute -> no new device read', await (async () => {
    let reads = 0; const g = w.geo.getCurrentPosition; w.geo.getCurrentPosition = (...a) => { reads++; g(...a); };
    await w.store.ensureFresh(); w.geo.getCurrentPosition = g; return reads === 0;
  })());
  check('call counts per screen', JSON.stringify(w.store.callCounts()) === JSON.stringify({ itinerary: 2, map: 1 }), JSON.stringify(w.store.callCounts()));
  check('logs: counts only, no coordinates', w.logs.every((l) => /^\[ROUTES\] screen=\w+ google_calls=\d+$/.test(l)), w.logs.join(' | '));
}

// ---- one at a time; quota -> paused, never an invented time
{
  const w = fakeWorld();
  w.fix = { ...ME, acc: 20 };
  await w.store.read();
  const dests = [0, 1, 2, 3].map((i) => ({ lat: AMER.lat + i * 0.01, lng: AMER.lng }));
  await Promise.all(dests.map((d) => w.store.route(d, 'drive', 'itinerary', true)));
  check('queued cards: one Google call at a time', w.maxInFlight === 1 && w.calls.length === 4, `max ${w.maxInFlight}`);
  w.queue = [Object.assign(new Error('Map search isn\'t available'), { status: 503 })];
  const far = { lat: 27.1, lng: 75.9 };
  let failedRoute = false;
  await w.store.route(far, 'drive', 'itinerary', true).catch(() => { failedRoute = true; });
  const before = w.calls.length;
  let paused = false;
  await w.store.route({ lat: 27.2, lng: 75.9 }, 'drive', 'itinerary', true).catch((e) => { paused = e instanceof S.RoutePausedError; });
  check('quota/paused -> error (card shows straight-line), later cards make no call', failedRoute && paused && w.calls.length === before);
  w.t += S.PAUSE_MS + 1;
  await w.store.route({ lat: 27.2, lng: 75.9 }, 'drive', 'itinerary', true);
  check('after the pause, calls resume', w.calls.length === before + 1);
}

// ---- grep: no previous-activity / hotel / trip-destination origin anywhere
const walk = (d) => readdirSync(d).flatMap((f) => { const p = join(d, f); return statSync(p).isDirectory() ? walk(p) : [p]; });
const files = walk(src).filter((f) => /\.(ts|tsx)$/.test(f));
const hits = (re) => files.filter((f) => re.test(readFileSync(f, 'utf8'))).map((f) => f.slice(src.length + 1));
check('no "from={prev}" travel legs', hits(/from=\{prev\}|<TravelLeg\b/).length === 0, hits(/from=\{prev\}|<TravelLeg\b/).join(','));
const computeUsers = hits(/\bcomputeRoute\(/);
check('computeRoute is called only by the device-location store (via routesApi)',
  computeUsers.every((f) => /services[\\/](routesApi|useDeviceLocation)\.ts$/.test(f)), computeUsers.join(','));
const backend = readFileSync(join(here, '..', '..', 'backend', 'voice', 'tools', 'lookups.py'), 'utf8');
const tt = backend.slice(backend.indexOf('def get_travel_time'), backend.indexOf('# ---------------- weather'));
check('voice get_travel_time: no trip-destination fallback', tt.length > 100 && !/_trip_destination|from_name|trip_dest/.test(tt));

console.log(`\n${total - failed}/${total} passed`);
process.exit(failed ? 1 : 0);
