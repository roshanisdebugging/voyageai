// "Add to itinerary" only inside the open trip's area (src/features/trip/tripArea.ts) and the map card's buttons
// (src/components/map/PlaceCardActions.tsx, rendered with react-dom/server). Run from frontend/: npm test
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { loadTs } from './tsload.mjs';

const src = join(dirname(fileURLToPath(import.meta.url)), '..', 'src');
const AREA = join(src, 'features', 'trip', 'tripArea.ts');
const warnings = [];
console.warn = (m) => warnings.push(String(m));

let failed = 0, total = 0;
const check = (name, ok, detail = '') => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail !== '' ? `  [${detail}]` : ''}`); };

const A = await loadTs(AREA);
const GOA = { id: 'trip_goa', destination: { name: 'Goa', latitude: 15.2993, longitude: 74.124 } };
const PANAJI = { latitude: 15.4989, longitude: 73.8278 };
const BIHAR = { latitude: 26.3537, longitude: 86.0718 };
const north = (km) => ({ latitude: 15.2993 + km / 111.195, longitude: 74.124 });   // due north of the destination

check('default radius is 60 km', A.TRIP_AREA_RADIUS_KM === 60);
check('inside: Panaji on a Goa trip', A.isPlaceInTripArea(PANAJI, GOA));
check('outside: Bihar on a Goa trip', !A.isPlaceInTripArea(BIHAR, GOA) && A.tripAreaResult(BIHAR, GOA) === 'outside');
check('edge: 59.9 km is inside', A.isPlaceInTripArea(north(59.9), GOA));
check('edge: 60.1 km is outside', !A.isPlaceInTripArea(north(60.1), GOA));
const badPlaces = [null, undefined, {}, { latitude: 15.3 }, { latitude: null, longitude: null }, { latitude: NaN, longitude: 74 },
  { latitude: '15.3', longitude: '74.1' }, { latitude: 0, longitude: 0 }, { latitude: 95, longitude: 74 }];
check('missing / bad place coordinates: not addable, and not called "outside"',
  badPlaces.every((p) => !A.isPlaceInTripArea(p, GOA) && A.tripAreaResult(p, GOA) === 'unknown'));
check('no open trip', [null, undefined, { id: 'x', destination: { name: ' ', latitude: 15.3, longitude: 74.1 } }]
  .every((t) => !A.isPlaceInTripArea(PANAJI, t) && A.tripAreaResult(PANAJI, t) === 'no_trip'));
check('no warnings so far', warnings.length === 0, warnings.join('|'));

const NO_COORDS = { id: 'trip_nc', destination: { name: 'Goa' } };
const itin = (...acts) => ({ days: [{ id: 'd1', dayNumber: 1, activities: acts.slice(0, 1) }, { id: 'd2', dayNumber: 2, activities: acts.slice(1) }] });
const acts = itin({ id: 'a', title: 'A', latitude: 15.55, longitude: 73.75 }, { id: 'b', title: 'B', latitude: 15.05, longitude: 74.0 }, { id: 'c', title: 'C' });
check('no destination coordinates: centroid of the activities, inside', A.isPlaceInTripArea(PANAJI, NO_COORDS, acts));
check('no destination coordinates: centroid of the activities, outside', A.tripAreaResult(BIHAR, NO_COORDS, acts) === 'outside');
check('destination coordinates win over the activities', A.isPlaceInTripArea(PANAJI, GOA, itin({ id: 'a', title: 'A', ...BIHAR })));
check('no warning while the centroid works', warnings.length === 0);
const none = [A.isPlaceInTripArea(PANAJI, NO_COORDS), A.isPlaceInTripArea(PANAJI, NO_COORDS, itin({ id: 'c', title: 'C' })), A.isPlaceInTripArea(BIHAR, NO_COORDS, null)];
check('no coordinates anywhere: false', none.every((r) => r === false));
check('... and logged exactly once for the trip', warnings.length === 1 && warnings[0].includes('trip_nc'), warnings.length);

check('already added: day found by ID and name', A.itineraryDayOf('b', 'B', acts) === 2);
check('already added: same ID, another name (generic act_1 IDs) is not a match', A.itineraryDayOf('b', 'Other', acts) === undefined);
check('already added: no itinerary', A.itineraryDayOf('b', 'B', null) === undefined);
check('highlight [lat, lng] pair', A.isPlaceInTripArea(A.coordsFromPair([15.4989, 73.8278]), GOA) && !A.isPlaceInTripArea(A.coordsFromPair(undefined), GOA));

globalThis.__viteEnv = { VITE_TRIP_AREA_RADIUS_KM: '10' };
const A10 = await loadTs(AREA);
check('VITE_TRIP_AREA_RADIUS_KM=10: Panaji is now outside', A10.TRIP_AREA_RADIUS_KM === 10 && !A10.isPlaceInTripArea(PANAJI, GOA));
globalThis.__viteEnv = { VITE_TRIP_AREA_RADIUS_KM: 'junk' };
check('bad VITE_TRIP_AREA_RADIUS_KM: default', (await loadTs(AREA)).TRIP_AREA_RADIUS_KM === 60);
globalThis.__viteEnv = {};

// The map card's button row, with the state useCanAddToTrip gives for each place (the real hook, its context faked).
globalThis.__trip = { currentTrip: null, currentItinerary: null };
const { useCanAddToTrip: addToTripHook } = await loadTs(join(src, 'features', 'trip', 'useCanAddToTrip.ts'), { './TripContext': 'export const useTrip = () => globalThis.__trip;' });
const { PlaceCardActions } = await loadTs(join(src, 'components', 'map', 'PlaceCardActions.tsx'));
const noop = () => {};
const card = (place, trip, itinerary = null, sessionDay = undefined) => {
  globalThis.__trip = { currentTrip: trip, currentItinerary: itinerary };
  const add = addToTripHook()({ id: 'ChIJtest', name: 'Test Place', ...place }, sessionDay);
  return renderToStaticMarkup(createElement(PlaceCardActions, { placeName: 'Test Place', add, saved: false, onAdd: noop, onToggleSave: noop, onDetails: noop }));
};
let html = card(BIHAR, GOA);
check('map card, outside: Save place, no Add', html.includes('Save place') && !html.includes('Add to Itinerary'));
check('map card, outside: muted hint', html.includes('Outside your Goa trip area'));
html = card(PANAJI, GOA);
check('map card, inside: Add, icon-only Save, no hint', html.includes('Add to Itinerary') && !html.includes('Save place') && html.includes('aria-label="Save Test Place"') && !html.includes('Outside your'));
html = card({}, GOA);
check('map card, place without coordinates: Save place, no Add, no "outside" claim', html.includes('Save place') && !html.includes('Add to Itinerary') && !html.includes('Outside your'));
html = card(PANAJI, null);
check('map card, no trip open: Save place, no Add, no hint', html.includes('Save place') && !html.includes('Add to Itinerary') && !html.includes('Outside your'));
html = card(BIHAR, GOA, null, 3);
check('map card, outside but added on this screen: Added to Day 3', html.includes('Added to Day 3') && !html.includes('Outside your') && html.includes('disabled'));
html = card(BIHAR, GOA, { days: [{ id: 'd2', dayNumber: 2, activities: [{ id: 'ChIJtest', title: 'Test Place' }] }] });
check('map card, outside but already in the itinerary: Added to Day 2', html.includes('Added to Day 2') && !html.includes('Add to Itinerary'));
html = card(PANAJI, { ...GOA, destination: { ...GOA.destination, name: 'Goa, India' } });
check('map card, inside with a long destination name', html.includes('Add to Itinerary'));

// The tour guide judges its own picked trip, not the open one.
globalThis.__trip = { currentTrip: { id: 'trip_bihar', destination: { name: 'Madhubani', ...BIHAR } }, currentItinerary: null };
const guide = addToTripHook({ trip: GOA, itinerary: null });
check('tour guide: the picked trip decides', guide({ id: 'c', name: 'C', ...PANAJI }).canAdd && !guide({ id: 'c', name: 'C', ...BIHAR }).showAdd);
check('tour guide: a card without coordinates gets no Add and no hint', !guide({ id: 'c', name: 'C' }).showAdd && guide({ id: 'c', name: 'C', latitude: null, longitude: null }).hint === null);

console.log(`\n${total - failed}/${total} passed`);
process.exit(failed ? 1 : 0);
