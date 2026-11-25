// Jarvis place cards (src/components/tour-guide/GuidePlaceCards.tsx): hours, rating, review count, order, 112/108 strip.
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadTs } from './tsload.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const { GuidePlaceCards } = await loadTs(join(here, '..', 'src', 'components', 'tour-guide', 'GuidePlaceCards.tsx'));
let failed = 0, total = 0;
const check = (name, ok, info = '') => {
  total += 1;
  if (!ok) failed += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${ok ? '' : `  [${info}]`}`);
};
const place = (over = {}) => ({ name: 'City Hospital', lat: 26.9, lng: 75.8, distance_m: 450, rating: 4.2, rating_count: 120,
  open_now: true, phone: null, address: null, maps_url: null, ...over });
const render = (places, emergency = false) =>
  renderToStaticMarkup(createElement(GuidePlaceCards, { places, emergency, onShowOnMap: () => {} }));

const unknown = render([place({ open_now: null })]);
check('unknown hours -> "Hours not available"', unknown.includes('Hours not available') && !unknown.includes('Open now') && !unknown.includes('Closed'));
check('... in muted text', /<span class="[^"]*text-\[var\(--guide-muted\)\][^"]*">Hours not available/.test(unknown), unknown);
const open = render([place()]);
check('open -> "Open now", no hours text', open.includes('Open now') && !open.includes('Hours not available'));
const closed = render([place({ open_now: false })]);
check('closed -> "Closed", no hours text', closed.includes('Closed') && !closed.includes('Hours not available'));

check('rating with its review count', open.includes('4.2 (120)') && !open.includes('Few reviews'));
const few = render([place({ rating: 5, rating_count: 2 })]);
check('under 5 reviews -> "Few reviews", still with the count', few.includes('5.0 (2)') && few.includes('Few reviews'), few);
check('4 reviews: few; 5 reviews: not', render([place({ rating_count: 4 })]).includes('Few reviews')
  && !render([place({ rating_count: 5 })]).includes('Few reviews'));
for (const rating_count of [null, undefined, 0]) {
  const html = render([place({ rating_count })]);
  check(`no review count (${rating_count}) -> no rating at all`, !html.includes('4.2') && !html.includes('Few reviews'));
}
check('no rating -> nothing', !render([place({ rating: null })]).includes('(120)'));

const list = render([place({ name: 'A open' }), place({ name: 'B unknown', open_now: null }), place({ name: 'C closed', open_now: false })], true);
check('cards keep the server order', list.indexOf('A open') < list.indexOf('B unknown') && list.indexOf('B unknown') < list.indexOf('C closed'));
check('112 / 108 strip kept for emergencies', list.includes('tel:112') && list.includes('tel:108') && !open.includes('tel:112'));
check('Google attribution kept', list.includes('Google Maps'));

console.log(`\n${total - failed}/${total} passed`);
if (failed) process.exit(1);
