// Unit tests for the map's pure logic (src/components/map/mapLogic.ts). Run from frontend/: npm test
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadTs } from './tsload.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const m = await loadTs(join(here, '..', 'src', 'components', 'map', 'mapLogic.ts'));
const cfg = await loadTs(join(here, '..', 'src', 'components', 'map', 'mapCategoryConfig.ts'));

let failed = 0, total = 0;
const check = (name, ok, detail = '') => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail !== '' ? `  [${detail}]` : ''}`); };
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// Category -> pin style (colours and icons from mapCategoryConfig.ts)
const food = m.pinStyle('restaurant', 'Rawat Mishthan');
check('restaurant -> food pin', food.category === 'food' && food.emoji === cfg.MAP_CATEGORY_CONFIG.food.emoji
  && food.color === cfg.MAP_CATEGORY_CONFIG.food.ring && food.ink === cfg.MAP_CATEGORY_CONFIG.food.dot, JSON.stringify(food));
check('lodging -> stays pin', m.pinStyle('lodging', 'ITC Rajputana').category === 'hotels');
check('hindu temple -> sights pin', m.pinStyle('Hindu Temple', 'Birla Mandir').category === 'sights');
check('market -> experiences pin', m.pinStyle('market', 'Johari Bazaar').category === 'experiences');
check('unknown -> sights pin (never empty)', m.pinStyle('', '').category === 'sights' && m.pinStyle('', '').emoji.length > 0);
const cats = ['sights', 'food', 'hotels', 'experiences'];
check('every category has its own colour', new Set(cats.map((c) => cfg.MAP_CATEGORY_CONFIG[c].ring)).size === 4);

// Cluster options / style
check('cluster sizes grow with the count', m.clusterStyle(3).size < m.clusterStyle(30).size && m.clusterStyle(30).size <= m.clusterStyle(80).size);
check('cluster label caps at 99+', m.clusterStyle(150).label === '99+' && m.clusterStyle(42).label === '42');
check('no clustering for a few places', !m.shouldCluster(5) && m.shouldCluster(40));
check('clusters break apart at street zoom', m.CLUSTER_OPTIONS.maxZoom <= 16 && m.CLUSTER_OPTIONS.radius > 0);

// Distance text
check('formatDistance metres', m.formatDistance(850) === '850 m away');
check('formatDistance km', m.formatDistance(4230) === '4.2 km away');
check('formatDistance unknown -> Nearby (no invented number)', m.formatDistance(undefined) === 'Nearby' && m.formatDistance(null) === 'Nearby' && m.formatDistance(NaN) === 'Nearby');
check('straight line: m / 1 decimal under 10 km / whole km', m.formatStraightLine(640) === '640 m' && m.formatStraightLine(4200) === '4.2 km' && m.formatStraightLine(239600) === '240 km');
const d = m.haversineMeters(26.9239, 75.8267, 27.1751, 78.0421); // Hawa Mahal -> Taj Mahal
check('haversine Jaipur -> Agra about 221 km', d > 215000 && d < 228000, d);
check('haversine same point = 0', m.haversineMeters(10, 10, 10, 10) === 0);

// Trip-open button rule
check('no trip open: Save + Details only', eq(m.placeActions(false), ['save', 'details']));
check('trip open: Add + Save + Details', eq(m.placeActions(true), ['add', 'save', 'details']));

// Map types and camera
check('map types: Map, Satellite, Terrain', eq(m.MAP_TYPES.map((t) => t.key), ['roadmap', 'satellite', 'terrain']));
check('easing ends at 0 and 1', m.easeInOutCubic(0) === 0 && m.easeInOutCubic(1) === 1 && m.easeInOutCubic(2) === 1);
check('fly zoom starts and ends where asked', m.flyZoom(12, 17, 50000, 0) === 12 && Math.abs(m.flyZoom(12, 17, 50000, 1) - 17) < 1e-9);
check('long hop dips out mid-flight, short hop does not', m.flyZoom(15, 15, 200000, 0.5) < 15 && m.flyZoom(15, 15, 500, 0.5) === 15);
check('fly duration bounded', m.flyDurationMs(10) >= 700 && m.flyDurationMs(5e6) <= 1800);

console.log(`\n${total - failed}/${total} passed`);
process.exit(failed ? 1 : 0);
