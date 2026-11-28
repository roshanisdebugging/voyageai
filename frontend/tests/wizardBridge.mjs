// Not a test: the backend end-to-end test (backend/tests/test_trip_purpose_e2e.py) runs the REAL frontend code
// through this script, so the wizard's path is covered without a browser.
//   node tests/wizardBridge.mjs voice '<prefill JSON>' <todayISO>  -> sanitizePrefill -> applyDraftToState -> payload
//   node tests/wizardBridge.mjs form  '<WizardState JSON>'          -> buildCreateTripPayload -> payload
// Prints the createTrip payload as JSON (what TripContext.createTrip sends to trips:create / POST /api/trips).
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadTs } from './tsload.mjs';

const src = join(dirname(fileURLToPath(import.meta.url)), '..', 'src');
const U = await loadTs(join(src, 'voice', 'uiActions.ts'));
const W = await loadTs(join(src, 'features', 'trip', 'wizardState.ts'));

// The wizard's first-render values (TripCreationWizard.tsx useState defaults).
const initial = (today) => ({
  destination: null, origin: null, startDate: today, endDate: today, adults: 2, children: 0, styles: [],
  budgetAmount: 30000, planCardId: undefined, purposeType: null, purposeText: '', baseArea: null,
});

const [mode, json, today] = process.argv.slice(2);
const input = JSON.parse(json);
let state;
if (mode === 'voice') {
  const draft = U.sanitizePrefill(input);
  if (!draft) throw new Error('prefill refused');
  state = W.applyDraftToState(initial(today), draft, today);
} else if (mode === 'form') {
  state = input;
} else {
  throw new Error(`unknown mode ${mode}`);
}
process.stdout.write(JSON.stringify(W.buildCreateTripPayload(state)));
