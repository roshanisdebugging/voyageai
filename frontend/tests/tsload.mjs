// Loads a TypeScript module (and the relative modules it imports) for plain-node tests:
// each file is transpiled with the TypeScript compiler into a temp folder, imports rewritten to .mjs.
import { readFileSync, writeFileSync, mkdtempSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname, basename, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import ts from 'typescript';

export async function loadTs(entry) {
  const out = mkdtempSync(join(tmpdir(), 'tsload-'));
  const done = new Set();
  const visit = (file) => {
    if (done.has(file)) return;
    done.add(file);
    let src = readFileSync(file, 'utf8');
    src = src.replace(/from '(\.{1,2}\/[^']+)'/g, (m, spec) => {
      if (/^import type /.test(m)) return m;
      const target = ['.ts', '.tsx'].map((ext) => resolve(dirname(file), spec + ext)).find(existsSync);
      if (!target) return m;
      visit(target);
      return `from './${basename(target).replace(/\.tsx?$/, '.mjs')}'`;
    });
    const js = ts.transpileModule(src, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
    writeFileSync(join(out, basename(file).replace(/\.tsx?$/, '.mjs')), js);
  };
  visit(resolve(entry));
  return import(pathToFileURL(join(out, basename(entry).replace(/\.tsx?$/, '.mjs'))).href);
}
