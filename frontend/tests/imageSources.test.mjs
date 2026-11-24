// Picture rules (src/utils/imageSources.ts): no invented photos, proxy URLs, placeholder on error. Run: npm test
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadTs } from './tsload.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const I = await loadTs(join(here, '..', 'src', 'utils', 'imageSources.ts'));

let failed = 0, total = 0;
const check = (name, ok, detail = '') => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail !== '' ? `  [${detail}]` : ''}`); };

const base = 'http://localhost:8000/';
check('proxy path gets the API base', I.resolveImageUrlWith(base, '/api/place-photo?name=places/x/photos/y&w=800&sig=s')
  === 'http://localhost:8000/api/place-photo?name=places/x/photos/y&w=800&sig=s');
check('https URL kept', I.resolveImageUrlWith(base, 'https://upload.wikimedia.org/a.jpg') === 'https://upload.wikimedia.org/a.jpg');
check('empty / null / junk -> null (placeholder)', [undefined, null, '', '  ', 'javascript:alert(1)', 'data:image/png;base64,xx', '/etc/passwd']
  .every((u) => I.resolveImageUrlWith(base, u) === null));

check('image shown until it fails', I.pickImageSrc('https://a/x.jpg', null) === 'https://a/x.jpg');
check('after onError for this src -> placeholder (null)', I.pickImageSrc('https://a/x.jpg', 'https://a/x.jpg') === null);
check('a new src after a failure is tried again', I.pickImageSrc('https://a/y.jpg', 'https://a/x.jpg') === 'https://a/y.jpg');
check('no src -> placeholder', I.pickImageSrc(null, null) === null);

check('cover: server picture with credit', JSON.stringify(I.tripCoverFrom({ coverMedia: { url: 'https://upload.wikimedia.org/c.jpg', provider: 'wikipedia', credit: 'Wikimedia Commons (CC BY-SA)', creditUrl: 'https://en.wikipedia.org/wiki/Hampi' } }))
  === JSON.stringify({ url: 'https://upload.wikimedia.org/c.jpg', source: 'wikipedia', credit: 'Wikimedia Commons (CC BY-SA)', creditUrl: 'https://en.wikipedia.org/wiki/Hampi' }));
check('cover: old generic "fallback" stock photo ignored', I.tripCoverFrom({ coverMedia: { url: 'https://images.unsplash.com/photo-1488646953014', provider: 'fallback' } }).url === null);
check('cover: provider none -> null', I.tripCoverFrom({ coverMedia: { url: '', provider: 'none' } }).url === null);
check('cover: no trip / no media -> null, never a guessed photo', I.tripCoverFrom(null).url === null && I.tripCoverFrom({ destination: { name: 'Goa' } }).url === null);

check('placeholder icons by category', I.placeholderKind('Food') === 'food' && I.placeholderKind('Sights') === 'heritage'
  && I.placeholderKind('Adventure') === 'nature' && I.placeholderKind('Festival') === 'festival' && I.placeholderKind('') === 'place');

check('credit: Google author', I.creditLabel({ source: 'google', credit: 'Ravi K' }) === 'Photo: Ravi K');
check('credit: Wikimedia', I.creditLabel({ source: 'wikipedia', credit: 'Wikimedia Commons (CC BY-SA)' }) === 'Wikimedia Commons (CC BY-SA)');
check('credit: Pexels', I.creditLabel({ source: 'pexels', credit: 'Photo by A B on Pexels' }) === 'Photo by A B on Pexels');
check('credit: none for unknown / no source', I.creditLabel({}) === null && I.creditLabel({ source: 'x', credit: 'y' }) === null);

console.log(`\n${total - failed}/${total} passed`);
process.exit(failed ? 1 : 0);
