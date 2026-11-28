// Trip purpose and base area on the wizard and review page (src/features/trip/tripPurpose.ts); the text rule has the
// same cases as backend tests/test_trip_purpose.py. Run from frontend/: npm test
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadTs } from './tsload.mjs';

const src = join(dirname(fileURLToPath(import.meta.url)), '..', 'src');
let failed = 0, total = 0;
const check = (name, ok, detail = '') => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail !== '' && !ok ? `  [${detail}]` : ''}`); };

const P = await loadTs(join(src, 'features', 'trip', 'tripPurpose.ts'));

check('five chips in order: Ghoomna, Kaam / Business, Event / Hackathon, Teerth, Kuch aur',
  JSON.stringify(P.PURPOSE_OPTIONS.map(o => o.label)) === JSON.stringify(['Ghoomna', 'Kaam / Business', 'Event / Hackathon', 'Teerth', 'Kuch aur']));
check('ids match the backend types', JSON.stringify(P.PURPOSE_OPTIONS.map(o => o.id)) === JSON.stringify(['leisure', 'business', 'event', 'pilgrimage', 'other']));
for (const [t, want] of [['business', true], ['event', true], ['other', true], ['leisure', false], ['pilgrimage', false], [null, false], [undefined, false]]) {
  check(`base area field shows for ${t}: ${want}`, P.showsBaseArea(t) === want);
}
check('isPurposeType', P.isPurposeType('event') && !P.isPurposeType('party') && !P.isPurposeType(null));

for (const [raw, want] of [['hackathon ke liye', 'hackathon ke liye'], ['  Team   offsite, day 2 ', 'Team offsite, day 2'],
  ['line\nbreak', 'line break'], ['x'.repeat(121), null], ['x'.repeat(120), 'x'.repeat(120)], ['quote " inside', null],
  ['<script>', null], ['{json}', null], ['12345', null], ['', null], [null, null], [42, null], ['हैकाथॉन के लिए', 'हैकाथॉन के लिए']]) {
  const got = P.cleanPurposeText(raw);
  check(`cleanPurposeText(${JSON.stringify(raw)?.slice(0, 20)}) === ${JSON.stringify(want)?.slice(0, 20)}`, got === want, got);
}
check('limit is 120', P.PURPOSE_TEXT_MAX === 120);

const AREA = { id: 'ChIJec', name: 'Electronic City', city: 'Bengaluru', latitude: 12.845, longitude: 77.66 };
const ev = P.purposePayload('event', ' hackathon  ke liye ', AREA);
check('event payload: type, cleaned text, area', ev.purposeType === 'event' && ev.purposeText === 'hackathon ke liye' && ev.baseArea === AREA);
const le = P.purposePayload('leisure', 'beach time', AREA);
check('leisure payload: no text, no area (planned as today)', le.purposeType === 'leisure' && le.purposeText === null && le.baseArea === null);
const pi = P.purposePayload('pilgrimage', '', AREA);
check('pilgrimage payload: no area', pi.baseArea === null && pi.purposeText === null);
check('empty text -> null', P.purposePayload('other', '   ', null).purposeText === null);

check('review: no problem for empty text', P.purposeTextProblem('') === null && P.purposeTextProblem('   ') === null);
check('review: problem for a bad text', (P.purposeTextProblem('a "quoted" text') || '').startsWith('Purpose:'));
check('review: fine text', P.purposeTextProblem('hackathon') === null);
check('review summary: "Event / Hackathon · near Electronic City"', P.purposeSummary('event', AREA) === 'Event / Hackathon · near Electronic City');
check('review summary: leisure never names an area', P.purposeSummary('leisure', AREA) === 'Ghoomna');
check('review summary: none chosen -> nothing (old trips / no purpose)', P.purposeSummary(null, null) === null && P.purposeSummary(undefined, AREA) === null);

console.log(`\n${total - failed}/${total} passed`);
process.exit(failed ? 1 : 0);
