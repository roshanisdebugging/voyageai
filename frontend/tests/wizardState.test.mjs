// The voice prefill -> wizard -> createTrip payload path (src/voice/uiActions.ts sanitizePrefill,
// src/features/trip/wizardState.ts). The purpose and base area used to be dropped by sanitizePrefill.
// Run from frontend/: npm test
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadTs } from './tsload.mjs';

const src = join(dirname(fileURLToPath(import.meta.url)), '..', 'src');
const U = await loadTs(join(src, 'voice', 'uiActions.ts'));
const W = await loadTs(join(src, 'features', 'trip', 'wizardState.ts'));
let failed = 0, total = 0;
const check = (name, ok, detail = '') => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail !== '' && !ok ? `  [${detail}]` : ''}`); };

const TODAY = '2026-11-28';
const BLR = { id: 'ChIJblr', name: 'Bengaluru', city: 'Bengaluru', region: 'Karnataka', country: 'India', latitude: 12.97, longitude: 77.59 };
const KOL = { id: 'ChIJkol', name: 'Kolkata', city: 'Kolkata', region: 'West Bengal', country: 'India', latitude: 22.57, longitude: 88.36 };
const EC = { id: 'ChIJec', name: 'Electronic City', city: 'Bengaluru', region: 'Karnataka', latitude: 12.845, longitude: 77.66 };
const PREFILL = { destination: BLR, origin: KOL, startDate: '2026-12-11', endDate: '2026-12-14', adultsCount: 1, childrenCount: 0,
  customBudgetAmount: 12000, purposeType: 'event', purposeText: 'hackathon ke liye', baseArea: EC };
const initial = () => ({ destination: null, origin: null, startDate: TODAY, endDate: TODAY, adults: 2, children: 0, styles: [],
  budgetAmount: 30000, planCardId: undefined, purposeType: null, purposeText: '', baseArea: null });

const sp = U.sanitizePrefill(PREFILL);
check('sanitizePrefill keeps purposeType', sp.purposeType === 'event', sp.purposeType);
check('sanitizePrefill keeps purposeText', sp.purposeText === 'hackathon ke liye', sp.purposeText);
check('sanitizePrefill keeps the base area (checked, India only)', sp.baseArea?.name === 'Electronic City' && sp.baseArea.latitude === 12.845);
const leisure = U.sanitizePrefill({ ...PREFILL, purposeType: 'leisure' });
check('leisure: no text, no area', leisure.purposeType === 'leisure' && leisure.purposeText === null && leisure.baseArea === null);
check('an unknown type is dropped (no purpose keys)', !('purposeType' in U.sanitizePrefill({ ...PREFILL, purposeType: 'party' })));
const old = U.sanitizePrefill({ ...PREFILL, purposeType: undefined, purposeText: undefined, baseArea: undefined });
check('an older prefill without a purpose: no purpose keys (the wizard keeps its own)', !('purposeType' in old) && !('baseArea' in old));
check('a bad text is dropped, the type kept', U.sanitizePrefill({ ...PREFILL, purposeText: 'a "quoted" text' }).purposeText === null);
check('an area outside India is dropped', U.sanitizePrefill({ ...PREFILL, baseArea: { name: 'London', latitude: 51.5, longitude: -0.12 } }).baseArea === null);

const st = W.applyDraftToState(initial(), sp, TODAY);
check('wizard state after the voice prefill: purpose, text, area', st.purposeType === 'event' && st.purposeText === 'hackathon ke liye'
  && st.baseArea?.name === 'Electronic City');
const payload = W.buildCreateTripPayload(st);
check('createTrip payload carries purposeType / purposeText / baseArea', payload.purposeType === 'event'
  && payload.purposeText === 'hackathon ke liye' && payload.baseArea?.id === 'ChIJec', JSON.stringify(Object.keys(payload)));
check('payload keys', JSON.stringify(Object.keys(payload).sort()) === JSON.stringify(['adultsCount', 'baseArea', 'budgetAmount',
  'childrenCount', 'destination', 'endDate', 'origin', 'purposeText', 'purposeType', 'startDate', 'tripStyle'].sort()), Object.keys(payload).join(','));
check('the rest of the draft as before', payload.destination.name === 'Bengaluru' && payload.origin.name === 'Kolkata'
  && payload.startDate === '2026-12-11' && payload.endDate === '2026-12-14' && payload.adultsCount === 1 && payload.budgetAmount === 12000);

const kept = W.applyDraftToState({ ...initial(), purposeType: 'business', purposeText: 'client visit', baseArea: EC },
  { destination: BLR }, TODAY);
check('a draft without purpose keys keeps the values already on the page', kept.purposeType === 'business'
  && kept.purposeText === 'client visit' && kept.baseArea === EC);
const noPurpose = W.buildCreateTripPayload({ ...initial(), destination: BLR });
check('no purpose chosen -> no purpose keys in the payload (as before)', !('purposeType' in noPurpose) && !('baseArea' in noPurpose));

console.log(`\n${total - failed}/${total} passed`);
process.exit(failed ? 1 : 0);
