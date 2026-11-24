// Loads a TypeScript module (and the relative modules it imports) for plain-node tests:
// each file is transpiled with the TypeScript compiler into a temp folder, imports rewritten to .mjs.
// A .tsx entry is written under node_modules so react / lucide-react resolve (removed on exit).
// import.meta.env reads globalThis.__viteEnv (empty unless the test sets it before loading).
import { readFileSync, writeFileSync, mkdtempSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname, basename, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import ts from 'typescript';

const NODE_MODULES = join(dirname(fileURLToPath(import.meta.url)), '..', 'node_modules');

// fakes: { './TripContext': 'export const useTrip = ...' } replaces a relative import with that source.
export async function loadTs(entry, fakes = {}) {
  const isTsx = entry.endsWith('.tsx');
  const out = mkdtempSync(join(isTsx ? NODE_MODULES : tmpdir(), isTsx ? '.tsload-' : 'tsload-'));
  if (isTsx) process.on('exit', () => rmSync(out, { recursive: true, force: true }));
  const done = new Set();
  const visit = (file) => {
    if (done.has(file)) return;
    done.add(file);
    let src = readFileSync(file, 'utf8').replace(/^import type [^;]*;/gm, '');
    src = src.replace(/from '(\.{1,2}\/[^']+)'/g, (m, spec) => {
      if (fakes[spec]) {
        writeFileSync(join(out, `${basename(spec)}.mjs`), fakes[spec]);
        return `from './${basename(spec)}.mjs'`;
      }
      const target = ['.ts', '.tsx'].map((ext) => resolve(dirname(file), spec + ext)).find(existsSync);
      if (!target) return m;
      visit(target);
      return `from './${basename(target).replace(/\.tsx?$/, '.mjs')}'`;
    });
    const js = ts.transpileModule(src, { compilerOptions: {
      module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
    } }).outputText.replaceAll('import.meta.env', '(globalThis.__viteEnv ?? {})');
    writeFileSync(join(out, basename(file).replace(/\.tsx?$/, '.mjs')), js);
  };
  visit(resolve(entry));
  return import(pathToFileURL(join(out, basename(entry).replace(/\.tsx?$/, '.mjs'))).href);
}
