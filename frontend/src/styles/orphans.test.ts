// orphans.test.ts — guards against dead code that nothing can reach.
//
// FEAT-118 moved the dashboard from src/pages/Dashboard.tsx to
// src/dashboard/Dashboard.tsx and decomposed it into widgets. The new files
// were added, but the originals were left behind: a component App.tsx no
// longer routes to, plus the pre-refactor, non-responsive stylesheet it
// imports — precisely the layout the feature existed to replace. Nothing
// failed. tsc type-checks unreferenced files happily, the bundler simply
// omits them, and the sibling guards here (overflow.test.ts, grid.test.ts)
// key off enumerated paths, so a *fork* of a file they already cover is
// invisible to them.
//
// The check walks the import graph from the entry point rather than asking
// "does anything reference this file?". That distinction is the whole point:
// the orphaned component imported the orphaned stylesheet, so the pair kept
// each other referenced and a reference-counting check reports nothing. Only
// reachability from a root distinguishes live code from a self-sustaining
// dead island.
//
// Specifiers are resolved to absolute paths, never compared by basename —
// the orphan and its live replacement were both named Dashboard.module.css,
// so a basename match would have been satisfied by the surviving copy.

import { existsSync, readFileSync, statSync } from 'fs';
import { dirname, resolve } from 'path';
import { describe, it, expect } from 'vitest';

import { findFiles, SRC_DIR, relPath } from './sourceFiles.test-helpers';

// The single root the bundler starts from. Everything the shipped app needs
// is reachable from here; anything else is, by definition, not shipped.
const ENTRY_POINT = resolve(SRC_DIR, 'index.tsx');

// Three edge shapes, because all three really occur here:
//   `from '...'`     — value imports, and CSS `composes ... from`
//   `import '...'`   — side-effect imports; how index.tsx pulls in the
//                      global tokens.css/globals.css, which have no binding
//   `import('...')`  — dynamic, how a lazily-loaded route would arrive
const STATIC_SPECIFIER = /from\s+['"](\.[^'"]+)['"]/g;
const SIDE_EFFECT_SPECIFIER = /import\s+['"](\.[^'"]+)['"]/g;
const DYNAMIC_SPECIFIER = /import\(\s*['"](\.[^'"]+)['"]\s*\)/g;

// Files that are legitimately unreachable from the entry point because they
// are never bundled: the test suite and the helpers it alone imports.
const NOT_SHIPPED = /(\.test\.tsx?|\.test-helpers\.ts|\.d\.ts|[/\\]setupTests\.ts)$/;

const SOURCE_EXTENSIONS = ['.ts', '.tsx', '.css'];

// Mirrors bundler resolution: exact path, then implicit extension, then a
// directory's index file (how the components/*/index.ts re-exports resolve).
function resolveSpecifier(fromFile: string, specifier: string): string | null {
  const base = resolve(dirname(fromFile), specifier);
  const candidates = [
    base,
    ...SOURCE_EXTENSIONS.map((ext) => base + ext),
    ...SOURCE_EXTENSIONS.map((ext) => resolve(base, `index${ext}`)),
  ];

  for (const candidate of candidates) {
    if (existsSync(candidate) && statSync(candidate).isFile()) return candidate;
  }
  return null;
}

function reachableFromEntryPoint(): Set<string> {
  const seen = new Set<string>();
  const queue = [ENTRY_POINT];

  while (queue.length > 0) {
    const current = queue.pop() as string;
    if (seen.has(current)) continue;
    seen.add(current);

    const content = readFileSync(current, 'utf-8');
    for (const pattern of [STATIC_SPECIFIER, SIDE_EFFECT_SPECIFIER, DYNAMIC_SPECIFIER]) {
      for (const [, specifier] of content.matchAll(pattern)) {
        const target = resolveSpecifier(current, specifier);
        if (target && !seen.has(target)) queue.push(target);
      }
    }
  }

  return seen;
}

function findOrphans(): string[] {
  const reachable = reachableFromEntryPoint();

  return findFiles(SRC_DIR, (name) => SOURCE_EXTENSIONS.some((ext) => name.endsWith(ext)))
    .filter((fullPath) => !NOT_SHIPPED.test(fullPath) && !reachable.has(fullPath))
    .map(
      (fullPath) =>
        `${relPath(fullPath)} — unreachable from src/index.tsx; ` +
        `delete it, or import it from code that ships`,
    )
    .sort();
}

describe('orphans.test.ts', () => {
  it('every shipped source file is reachable from the entry point', () => {
    expect(findOrphans()).toEqual([]);
  });
});
