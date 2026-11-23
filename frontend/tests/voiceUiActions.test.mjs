// Voice ui_actions: the map_results action ("Hawa Mahal ke paas restaurant") is strictly checked. Run from frontend/: npm test
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadTs } from './tsload.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const U = await loadTs(join(here, '..', 'src', 'voice', 'uiActions.ts'));

let failed = 0, total = 0;
const check = (name, ok, detail = '') => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail !== '' ? `  [${detail}]` : ''}`); };

const good = (i) => ({ name: `Cafe ${i}`, lat: 26.92 + i / 1000, lng: 75.82, place_id: `ChIJcafe${i}`, rating: 4.3, address: 'Jaipur', category: 'restaurant' });
const places = [good(1), good(2)];
let got = null;
const ran = U.runUiActions([{ type: 'map_results', title: 'Hawa Mahal ke paas restaurants', places }, { type: 'navigate', to: '/map' }],
  { navigate: () => {}, mapResults: (r) => { got = r; } });
check('map_results + navigate both run', ran === 2, ran);
check('handler gets the title and places', got && got.title === 'Hawa Mahal ke paas restaurants' && got.places.length === 2
  && got.places[0].placeId === 'ChIJcafe1' && got.places[0].rating === 4.3 && got.places[0].category === 'restaurant', JSON.stringify(got));

const mixed = U.checkedMapResults([
  good(1),
  { name: 'Dubai', lat: 25.2, lng: 55.27 },                       // outside India
  { name: '', lat: 26.9, lng: 75.8 },                             // no name
  { name: 'Bad id', lat: 26.9, lng: 75.8, place_id: '../x' },     // id dropped, place kept
  { name: 'Bad rating', lat: 26.9, lng: 75.8, rating: 9 },        // rating dropped
  'not an object',
]);
check('only well-formed places in India are kept', mixed.length === 3 && mixed.map((p) => p.name).join('|') === 'Cafe 1|Bad id|Bad rating',
  JSON.stringify(mixed));
check('a bad place id / rating is dropped, not trusted', mixed[1].placeId === undefined && mixed[2].rating === undefined);
check('at most 6 places', U.checkedMapResults(Array.from({ length: 10 }, (_, i) => good(i))).length === U.MAX_MAP_RESULTS && U.MAX_MAP_RESULTS === 6);
got = null;
check('no valid places -> the action is ignored', U.runUiActions([{ type: 'map_results', title: 'x', places: [{ name: 'Dubai', lat: 25.2, lng: 55.27 }] }],
  { navigate: () => {}, mapResults: (r) => { got = r; } }) === 0 && got === null);
check('no title -> ignored', U.runUiActions([{ type: 'map_results', places }], { navigate: () => {}, mapResults: () => {} }) === 0);

console.log(`\n${total - failed}/${total} passed`);
process.exit(failed ? 1 : 0);
