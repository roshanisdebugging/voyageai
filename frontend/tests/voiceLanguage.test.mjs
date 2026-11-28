// The voice language selector (src/voice/voiceLanguage.ts): the value, its persistence across reloads, and that it is
// sent with every voice turn and Confirm / Cancel tap (src/voice/voiceSocket.ts). Run from frontend/: npm test
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadTs } from './tsload.mjs';

const src = join(dirname(fileURLToPath(import.meta.url)), '..', 'src');
let failed = 0, total = 0;
const check = (name, ok, detail = '') => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail !== '' && !ok ? `  [${detail}]` : ''}`); };

// A browser-like window: localStorage that survives "reloads" (a new module instance reading the same store).
class Store {
  constructor() { this.data = new Map(); }
  getItem(k) { return this.data.has(k) ? this.data.get(k) : null; }
  setItem(k, v) { this.data.set(k, String(v)); }
  removeItem(k) { this.data.delete(k); }
  clear() { this.data.clear(); }
}
const store = new Store();
const events = [];
globalThis.window = { localStorage: store, dispatchEvent: (e) => events.push(e), addEventListener() {}, removeEventListener() {} };
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init?.detail; } };

const V = await loadTs(join(src, 'voice', 'voiceLanguage.ts'));

check('options: Auto, हिन्दी, English (in that order)', JSON.stringify(V.VOICE_LANGUAGES.map(o => [o.id, o.label]))
  === JSON.stringify([['auto', 'Auto'], ['hi', 'हिन्दी'], ['en', 'English']]));
check('default: auto', V.getVoiceLanguage() === 'auto');
for (const [raw, want] of [['hi', 'hi'], ['en', 'en'], ['auto', 'auto'], ['fr', 'auto'], ['', 'auto'], [null, 'auto'], [7, 'auto'], ['HI', 'auto']]) {
  check(`sanitize ${JSON.stringify(raw)} -> ${want}`, V.sanitizeVoiceLanguage(raw) === want);
}
check('set hi: stored under cruiser_voice_language', V.setVoiceLanguage('hi') === 'hi' && store.getItem('cruiser_voice_language') === 'hi');
check('set hi: a change event for the other selector', events.at(-1)?.type === V.VOICE_LANGUAGE_CHANGED && events.at(-1)?.detail === 'hi');
check('read back: hi', V.getVoiceLanguage() === 'hi');
check('a tampered stored value reads as auto', (store.setItem('cruiser_voice_language', 'klingon'), V.getVoiceLanguage() === 'auto'));
V.setVoiceLanguage('en');
check('mic control cycles Auto -> हिन्दी -> English -> Auto', V.nextVoiceLanguage('auto') === 'hi' && V.nextVoiceLanguage('hi') === 'en'
  && V.nextVoiceLanguage('en') === 'auto');
const broken = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };
check('blocked storage: the choice still works for this page (memory)', V.setVoiceLanguage('hi', broken) === 'hi'
  && V.getVoiceLanguage(broken) === 'hi');
V.setVoiceLanguage('en');

// main.tsx wipes localStorage on every load except a keep-list: the voice language must be on it.
const mainSrc = readFileSync(join(src, 'main.tsx'), 'utf8');
check('main.tsx keeps the voice language through its storage wipe', /for \(const key of \[[^\]]*VOICE_LANGUAGE_KEY/.test(mainSrc));
// a "reload": the wipe keeps the key, a new module instance reads it
const kept = store.getItem('cruiser_voice_language');
store.clear();
store.setItem('cruiser_voice_language', kept);
const V2 = await loadTs(join(src, 'voice', 'voiceLanguage.ts'));
check('after a reload: still English', V2.getVoiceLanguage() === 'en', V2.getVoiceLanguage());

// voiceSocket sends it: start, confirm and cancel carry `language`, read at the time of the call.
globalThis.WebSocket = { OPEN: 1 };
const S = await loadTs(join(src, 'voice', 'voiceSocket.ts'), {
  '../config/apiConfig': 'export const getAuthToken = () => null; export const getWsBaseUrl = () => "ws://test";',
});
const sent = [];
S.voiceSocket.ws = { readyState: 1, send: (x) => sent.push(JSON.parse(x)) };
S.voiceSocket.start('conv1', '/home', null, null, null);
check('start carries language "en"', sent.at(-1)?.type === 'start' && sent.at(-1)?.language === 'en', JSON.stringify(sent.at(-1)));
store.setItem('cruiser_voice_language', 'hi');
S.voiceSocket.start('conv1', '/home', null, null, null);
check('a change applies from the next turn: start carries "hi"', sent.at(-1)?.language === 'hi', JSON.stringify(sent.at(-1)));
S.voiceSocket.confirm('conv1', 'p1', null);
S.voiceSocket.cancel('conv1', 'p1');
check('confirm and cancel carry it too', sent.at(-2)?.type === 'confirm' && sent.at(-2)?.language === 'hi'
  && sent.at(-1)?.type === 'cancel' && sent.at(-1)?.language === 'hi');
store.setItem('cruiser_voice_language', 'auto');
S.voiceSocket.start('conv1', '/home', null, null, null);
check('auto is sent as "auto" (the server keeps the old behaviour)', sent.at(-1)?.language === 'auto');
S.voiceSocket.ws = null;

console.log(`\n${total - failed}/${total} passed`);
process.exit(failed ? 1 : 0);
