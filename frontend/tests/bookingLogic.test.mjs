// Booking stage 2 screen helpers (the server checks every answer; these shape what is typed). Run from frontend/: npm test
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadTs } from './tsload.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const B = await loadTs(join(here, '..', 'src', 'features', 'booking', 'bookingLogic.ts'));
const U = await loadTs(join(here, '..', 'src', 'voice', 'uiActions.ts'));

let failed = 0, total = 0;
const check = (name, ok, detail = '') => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail !== '' ? `  [${detail}]` : ''}`); };

check('card: ready, upcoming, not dismissed -> shown', B.bookingCardVisible('READY', false, false) === true);
check('card: plan still generating / failed -> hidden', !B.bookingCardVisible('GENERATING', false, false) && !B.bookingCardVisible('FAILED', false, false));
check('card: past trip -> hidden', !B.bookingCardVisible('READY', true, false));
check('card: "Abhi nahi" -> hidden', !B.bookingCardVisible('READY', false, true));
check('phone field: letters dropped while typing, + and spaces kept', B.cleanPhoneInput('+91 98765abc43210') === '+91 9876543210');
check('phone field: at most 16 characters', B.cleanPhoneInput('1'.repeat(30)).length === 16);
check('age field: digits only, at most 3', B.cleanAgeInput('3a4x') === '34' && B.cleanAgeInput('12345') === '123');
check('name: Roman and Devanagari names', B.looksLikeName('Rahul Sharma') && B.looksLikeName('राहुल शर्मा'));
check('name: digits / symbols / one letter / too long refused',
  !B.looksLikeName('Rahul123') && !B.looksLikeName('R@hul') && !B.looksLikeName('R') && !B.looksLikeName('A'.repeat(61)));
check('name: Ol Chiki / Bengali / Tamil -> "script"', ['ᱩᱢᱟᱱᱟᱛᱷ', 'রাহুল', 'ராகுல்'].every((x) => B.nameProblem(x) === 'script'));
check("name: . - ' and accents allowed", ["R. K. Singh", "D'Souza", 'Anne-Marie', 'José', 'श्री राम'].every((x) => B.nameProblem(x) === null));
check('name: Devanagari digits refused', B.nameProblem('राम२') === 'invalid');
check('name messages', B.NAME_MESSAGES.script === 'Naam English ya Hindi mein likhiye.');
check('services: toggle keeps the fixed order', B.toggleService(['hotel'], 'flight').join() === 'flight,hotel'
  && B.toggleService(['flight', 'hotel'], 'flight').join() === 'hotel' && B.toggleService([], 'cab').length === 0);

// Voice: refresh "booking" is allowlisted and becomes a window event (no other voice client change).
const fired = [];
globalThis.window = { dispatchEvent: (e) => { fired.push(e.type); return true; } };
globalThis.Event = globalThis.Event || class { constructor(t) { this.type = t; } };
let refreshed = null;
const ran = U.runUiActions([{ type: 'refresh', what: 'booking' }], { navigate: () => {}, refresh: (w) => { refreshed = w; } });
check('voice refresh "booking" -> BOOKING_CHANGED event, not the old refresh handler',
  ran === 1 && fired.join() === U.BOOKING_CHANGED && refreshed === null, JSON.stringify(fired));
check('voice refresh "itinerary" still uses the old handler', U.runUiActions([{ type: 'refresh', what: 'itinerary' }],
  { navigate: () => {}, refresh: (w) => { refreshed = w; } }) === 1 && refreshed === 'itinerary');
check('voice refresh of an unknown thing is ignored', U.runUiActions([{ type: 'refresh', what: 'bookings_all' }],
  { navigate: () => {}, refresh: () => {} }) === 0);
// Opening the booking screen by voice: allowlisted, skipped when it is already open.
let went = null;
globalThis.window = { location: { pathname: '/trip' }, dispatchEvent: () => true };
check('navigate /trip/booking is allowed', U.isAllowedRoute('/trip/booking')
  && U.runUiActions([{ type: 'navigate', to: '/trip/booking' }], { navigate: (to) => { went = to; } }) === 1 && went === '/trip/booking');
went = null;
globalThis.window.location.pathname = '/trip/booking';
check('navigate /trip/booking skipped when the screen is already open', U.runUiActions([{ type: 'navigate', to: '/trip/booking' }],
  { navigate: (to) => { went = to; } }) === 0 && went === null);
check('other navigations are unchanged on the booking screen', U.runUiActions([{ type: 'navigate', to: '/map' }],
  { navigate: (to) => { went = to; } }) === 1 && went === '/map');
delete globalThis.window;

// Live card highlight: only rows whose value changed, nothing on the first view, never a '-' row.
const rows = (o) => Object.entries(o).map(([key, value]) => ({ key, label: key, value, current: false }));
check('card: first view highlights nothing', B.changedKeys(null, rows({ services: 'Hotel', hotel_type: '-' })).length === 0);
check('card: the newly answered row is highlighted', B.changedKeys({ services: 'Hotel', hotel_type: '-' },
  rows({ services: 'Hotel', hotel_type: '3-star' })).join() === 'hotel_type');
check('card: a row going back to "-" (Back) is not highlighted', B.changedKeys({ hotel_type: '3-star' }, rows({ hotel_type: '-' })).length === 0);
check('card: values map', JSON.stringify(B.rowValues(rows({ a: '1', b: '-' }))) === '{"a":"1","b":"-"}');

check('status line for an open request', B.requestLine({ requestNo: 'BR-1001', statusLabel: 'Save ho gayi' }) === 'Request BR-1001: Save ho gayi');
check('no request -> no status line', B.requestLine(null) === null && B.requestLine({}) === null);
check('partner email: poll only while sending', B.notifyPending({ notify: 'sending' }) === true
  && ['sent', 'failed', 'off', undefined].every((n) => B.notifyPending({ notify: n }) === false) && B.notifyPending(null) === false);
console.log(`\n${total - failed}/${total} passed`);
process.exit(failed ? 1 : 0);
