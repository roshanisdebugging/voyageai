// The starting city's name rule (src/features/trip/originName.ts), same cases as backend tests/test_voice_origin.py.
// Run from frontend/: npm test
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadTs } from './tsload.mjs';

const src = join(dirname(fileURLToPath(import.meta.url)), '..', 'src');
let failed = 0, total = 0;
const check = (name, ok, detail = '') => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail !== '' ? `  [${detail}]` : ''}`); };

const O = await loadTs(join(src, 'features', 'trip', 'originName.ts'));
for (const [raw, want] of [['Kolkata', 'Kolkata'], ['  New   Delhi ', 'New Delhi'], ['कोलकाता', 'कोलकाता'], ['Port Blair', 'Port Blair'],
  ['St. Thomas Mount', 'St. Thomas Mount'], ['Daman & Diu', 'Daman & Diu'], ['12345', null], ['Sector 17', null], ['', null],
  ['K', null], ['x'.repeat(61), null], [12, null], [null, null], ['Kolkata!!', null], ['<script>', null], ['--', null]]) {
  const got = O.cleanOriginName(raw);
  check(`cleanOriginName(${JSON.stringify(raw).slice(0, 20)}) === ${JSON.stringify(want)}`, got === want, got);
}
check('limit is 60', O.ORIGIN_MAX_CHARS === 60);
console.log(`\n${total - failed}/${total} passed`);
if (failed) process.exit(1);
