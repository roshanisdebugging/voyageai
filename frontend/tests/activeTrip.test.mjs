// Unit test for the shared "is a trip open" check (src/features/trip/activeTrip.ts).
// The frontend has no test runner: the file is transpiled with the TypeScript compiler and imported.
// Run from frontend/: npm test
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import ts from 'typescript';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, '..', 'src', 'features', 'trip', 'activeTrip.ts'), 'utf8');
const js = ts.transpileModule(src, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
const out = join(mkdtempSync(join(tmpdir(), 'activetrip-')), 'activeTrip.mjs');
writeFileSync(out, js);
const { hasActiveTrip } = await import(pathToFileURL(out).href);

const cases = [
  ['no trip (null)', null, false],
  ['no trip (undefined)', undefined, false],
  ['trip with a destination', { id: 'trip_1', destination: { name: 'Jaipur', country: 'India' } }, true],
  ['trip without a destination', { id: 'trip_2', destination: undefined }, false],
  ['trip with an empty destination name', { id: 'trip_3', destination: { name: '' } }, false],
  ['trip with a blank destination name', { id: 'trip_4', destination: { name: '   ' } }, false],
];
let failed = 0;
for (const [name, trip, want] of cases) {
  const got = hasActiveTrip(trip);
  const ok = got === want;
  if (!ok) failed++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name} -> ${got}`);
}
console.log(`\n${cases.length - failed}/${cases.length} passed`);
process.exit(failed ? 1 : 0);
