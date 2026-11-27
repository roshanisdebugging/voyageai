// Place-check labels on itinerary activities (backend place_verify.py). Run from frontend/: npm test
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadTs } from './tsload.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const V = await loadTs(join(here, '..', 'src', 'components', 'itinerary', 'placeVerify.ts'));

let failed = 0, total = 0;
const check = (name, ok, detail = '') => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail !== '' ? `  [${detail}]` : ''}`); };

check('verified -> "Found on Google"', V.placeVerifyLabel('verified')?.text === 'Found on Google');
check('not_found -> "Not found on Google"', V.placeVerifyLabel('not_found')?.text === 'Not found on Google');
check('far -> "Far from the rest of this day"', V.placeVerifyLabel('far')?.text === 'Far from the rest of this day');
check('not checked (null / missing / older trips) -> no label', [null, undefined, '', 'other'].every((s) => V.placeVerifyLabel(s) === null));
check('not_found and far are warnings, verified is not', V.placeVerifyLabel('not_found').tone === 'warn'
  && V.placeVerifyLabel('far').tone === 'warn' && V.placeVerifyLabel('verified').tone === 'ok');

console.log(`\n${total - failed}/${total} passed`);
process.exit(failed ? 1 : 0);
