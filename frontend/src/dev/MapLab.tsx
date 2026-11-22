/**
 * DEV ONLY: /dev/map-lab (not linked in the app, not in production builds).
 * Tests each Google Maps JavaScript feature on its own with the real browser key and shows PASS/FAIL with the
 * error. Map stage 2 enables only what passes here.
 */
import React, { useEffect, useRef, useState } from 'react';
import { MarkerClusterer } from '@googlemaps/markerclusterer';
import { GOOGLE_MAPS_KEY, MAP_ID, loadGoogleLibrary, onMapsAuthFailure } from '../components/map/googleMapsLoader';

type Status = 'RUNNING' | 'PASS' | 'FAIL' | 'SKIP';
interface Row { id: string; name: string; status: Status; detail: string }

const JAIPUR = { lat: 26.9239, lng: 75.8267 };
const TIMEOUT_MS = 15000;

// Google prints its errors to the console; keep the ones seen during each test (never the key).
const googleErrors: string[] = [];
const origError = console.error.bind(console);
console.error = (...args: unknown[]) => {
  const text = args.map((a) => (a instanceof Error ? a.message : String(a))).join(' ');
  if (/google|maps|gmp|places/i.test(text)) googleErrors.push(GOOGLE_MAPS_KEY ? text.split(GOOGLE_MAPS_KEY).join('<key>') : text);
  origError(...args);
};

function withTimeout<T>(p: Promise<T>, what: string): Promise<T> {
  return Promise.race([p, new Promise<T>((_, rej) => setTimeout(() => rej(new Error(`timeout waiting for ${what}`)), TIMEOUT_MS))]);
}

function once(target: google.maps.MVCObject, event: string): Promise<void> {
  return new Promise((res) => google.maps.event.addListenerOnce(target, event, () => res()));
}

function box(host: HTMLElement): HTMLDivElement {
  const d = document.createElement('div');
  d.style.cssText = 'width:320px;height:200px;display:inline-block;margin:4px;border:1px solid #ccc;vertical-align:top';
  host.appendChild(d);
  return d;
}

async function newMap(host: HTMLElement, opts: google.maps.MapOptions = {}) {
  const { Map } = await loadGoogleLibrary('maps');
  const map = new Map(box(host), { center: JAIPUR, zoom: 15, mapId: MAP_ID, renderingType: google.maps.RenderingType.VECTOR, ...opts });
  await withTimeout(once(map, 'tilesloaded'), 'tiles');
  return map;
}

type Test = { id: string; name: string; run: (host: HTMLElement) => Promise<string> };

const TESTS: Test[] = [
  {
    id: 'vector', name: 'Vector map with DEMO_MAP_ID',
    run: async (host) => {
      const map = await newMap(host);
      const type = map.getRenderingType();
      if (type !== google.maps.RenderingType.VECTOR) throw new Error(`rendering type is ${type}`);
      return 'rendering type VECTOR';
    },
  },
  {
    id: 'colorScheme', name: 'Built-in colorScheme light / dark',
    run: async (host) => {
      const { ColorScheme } = await loadGoogleLibrary('core');
      await newMap(host, { colorScheme: ColorScheme.LIGHT });
      await newMap(host, { colorScheme: ColorScheme.DARK });
      return 'LIGHT and DARK maps loaded';
    },
  },
  {
    id: 'advancedMarker', name: 'Advanced markers with custom HTML',
    run: async (host) => {
      const map = await newMap(host);
      const { AdvancedMarkerElement } = await loadGoogleLibrary('marker');
      const pin = document.createElement('div');
      pin.textContent = '🛕';
      pin.style.cssText = 'font-size:22px;background:#E8A33D;border-radius:50%;padding:4px';
      const marker = new AdvancedMarkerElement({ map, position: JAIPUR, content: pin, title: 'test' });
      await new Promise((r) => setTimeout(r, 1500));
      if (!pin.isConnected) throw new Error('custom HTML pin not attached to the page');
      return `HTML pin in the DOM (marker map set: ${Boolean(marker.map)})`;
    },
  },
  {
    id: 'clusterer', name: '@googlemaps/markerclusterer',
    run: async (host) => {
      const map = await newMap(host, { zoom: 11 });
      const { AdvancedMarkerElement } = await loadGoogleLibrary('marker');
      const markers = Array.from({ length: 40 }, (_, i) => new AdvancedMarkerElement({
        position: { lat: JAIPUR.lat + (Math.sin(i) * 0.05), lng: JAIPUR.lng + (Math.cos(i * 1.3) * 0.05) },
      }));
      let clusters = 0;
      const done = new Promise<void>((res) => {
        new MarkerClusterer({ map, markers, onClusterClick: () => {}, renderer: undefined }).addListener('clusteringend', (mc: { clusters?: unknown[] }) => {
          clusters = mc.clusters?.length ?? 0;
          res();
        });
      });
      await withTimeout(done, 'clusteringend');
      if (!clusters) throw new Error('no clusters');
      return `40 markers -> ${clusters} clusters`;
    },
  },
  {
    id: 'tilt', name: 'Tilt and heading',
    run: async (host) => {
      const map = await newMap(host, { zoom: 18, tiltInteractionEnabled: true, headingInteractionEnabled: true });
      map.setTilt(45);
      map.setHeading(90);
      await withTimeout(once(map, 'idle'), 'idle');
      const tilt = map.getTilt(); const heading = map.getHeading();
      if (!tilt || tilt < 30) throw new Error(`tilt stayed ${tilt}`);
      return `tilt ${tilt}, heading ${heading}`;
    },
  },
  {
    id: 'mapTypes', name: 'Satellite and terrain map types',
    run: async (host) => {
      const sat = await newMap(host, { mapTypeId: 'satellite' });
      const ter = await newMap(host, { mapTypeId: 'terrain', zoom: 9 });
      return `satellite: ${sat.getMapTypeId()}, terrain: ${ter.getMapTypeId()}`;
    },
  },
  {
    id: 'maps3d', name: '3D Maps element (maps3d)',
    run: async (host) => {
      const lib = await loadGoogleLibrary('maps3d') as unknown as { Map3DElement: new (o: object) => HTMLElement };
      const el = new lib.Map3DElement({ center: { lat: JAIPUR.lat, lng: JAIPUR.lng, altitude: 400 }, range: 1500, tilt: 60, mode: 'SATELLITE' });
      el.style.cssText = 'width:320px;height:200px;display:inline-block;margin:4px';
      host.appendChild(el);
      const result = await withTimeout(new Promise<string>((res, rej) => {
        el.addEventListener('gmp-steadychange', () => res('steady (3D tiles rendered)'));
        el.addEventListener('gmp-error', () => rej(new Error('gmp-error from Map3DElement')));
      }), 'gmp-steadychange');
      return result;
    },
  },
  {
    id: 'placesUiKit', name: 'Places UI Kit (place details compact)',
    run: async (host) => {
      await loadGoogleLibrary('places');
      const params = new URLSearchParams(window.location.search);
      const placeId = params.get('place') || '';
      if (!placeId) throw new Error('no ?place=<Google place ID> given');
      const el = document.createElement('gmp-place-details-compact');
      const req = document.createElement('gmp-place-details-place-request');
      req.setAttribute('place', placeId);
      el.appendChild(req);
      el.appendChild(document.createElement('gmp-place-all-content'));
      const wrap = box(host);
      wrap.style.height = 'auto';
      wrap.appendChild(el);
      return await withTimeout(new Promise<string>((res, rej) => {
        el.addEventListener('gmp-load', () => res('details compact element loaded'));
        el.addEventListener('gmp-error', () => rej(new Error('gmp-error from the Places UI Kit element')));
        el.addEventListener('gmp-requesterror', () => rej(new Error('gmp-requesterror from the Places UI Kit element')));
      }), 'gmp-load');
    },
  },
];

function webglInfo(): string {
  const c = document.createElement('canvas');
  const gl2 = c.getContext('webgl2');
  const strict = document.createElement('canvas').getContext('webgl2', { failIfMajorPerformanceCaveat: true });
  return `WebGL2: ${gl2 ? 'yes' : 'no'}, without performance caveat: ${strict ? 'yes' : 'no (software GPU)'}`;
}

const MapLab: React.FC = () => {
  const [rows, setRows] = useState<Row[]>(TESTS.map((t) => ({ id: t.id, name: t.name, status: 'RUNNING', detail: '' })));
  const hostRef = useRef<HTMLDivElement>(null);
  const [authFailure, setAuthFailure] = useState(false);

  useEffect(() => onMapsAuthFailure(() => setAuthFailure(true)), []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      for (const t of TESTS) {
        if (cancelled) return;
        const host = hostRef.current!;
        const section = document.createElement('div');
        section.dataset.test = t.id;
        host.appendChild(section);
        const errorsBefore = googleErrors.length;
        let status: Status = 'PASS';
        let detail = '';
        try {
          detail = await t.run(section);
          await new Promise((r) => setTimeout(r, 800)); // let late Google console errors arrive
          const late = googleErrors.slice(errorsBefore);
          if (late.length) { status = 'FAIL'; detail = `${detail}; Google error: ${late.join(' | ').slice(0, 300)}`; }
        } catch (err) {
          status = 'FAIL';
          const late = googleErrors.slice(errorsBefore);
          detail = `${err instanceof Error ? err.message : String(err)}${late.length ? `; Google error: ${late.join(' | ').slice(0, 300)}` : ''}`;
        }
        if (!cancelled) setRows((rs) => rs.map((r) => (r.id === t.id ? { ...r, status, detail } : r)));
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <div style={{ padding: 16, fontFamily: 'system-ui', background: '#fff', color: '#111', minHeight: '100vh', overflow: 'auto' }}>
      <h1 style={{ fontSize: 20, fontWeight: 700 }}>Map lab (dev only)</h1>
      <p>Key present: {GOOGLE_MAPS_KEY ? 'yes' : 'NO (set VITE_GOOGLE_MAPS_BROWSER_KEY)'} · gm_authFailure: {authFailure ? 'YES' : 'no'} · {webglInfo()}</p>
      <table data-testid="probe" style={{ borderCollapse: 'collapse', margin: '12px 0' }}>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} data-probe={r.id} data-status={r.status}>
              <td style={{ border: '1px solid #ccc', padding: 4 }}>{r.name}</td>
              <td style={{ border: '1px solid #ccc', padding: 4, fontWeight: 700, color: r.status === 'PASS' ? 'green' : r.status === 'FAIL' ? 'crimson' : '#555' }}>{r.status}</td>
              <td style={{ border: '1px solid #ccc', padding: 4, fontSize: 12 }}>{r.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div ref={hostRef} />
    </div>
  );
};

export default MapLab;
