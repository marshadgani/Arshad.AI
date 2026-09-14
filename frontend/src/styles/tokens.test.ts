import { readFileSync } from 'fs';
import { resolve } from 'path';

import { findCssFiles, findFiles, relPath, SRC_DIR } from './sourceFiles.test-helpers';

// Guards against the exact bug FEAT-143's gate caught: a CSS Module
// referencing var(--surface, #161b22) where --surface was never defined in
// tokens.css, so the custom property silently and permanently resolved to
// the hardcoded fallback instead of the app's real theme — with no error,
// no lint warning, and every existing test still green. Walks every
// *.module.css file, globals.css, and every .ts/.tsx source in src/ (FEAT-144
// shipped this scoped to *.module.css only; FEAT-145 widened it after gate
// agents found inline var(--x) in .tsx style props and healthFormat.ts were
// unguarded) so a future reference to an undefined token — wherever it's
// written — fails loudly instead of shipping unnoticed.

const TOKENS_FILE = resolve(SRC_DIR, 'styles/tokens.css');
const GLOBALS_FILE = resolve(SRC_DIR, 'styles/globals.css');
const VAR_REFERENCE = /var\(\s*(--[a-zA-Z0-9-]+)/g;

// Excludes test files (and their shared helpers) so this suite's own
// fixture below — a deliberately undefined var(--x) used to prove the
// detector works — isn't also picked up as a second, unrelated violation
// when this file itself gets walked as a .ts source. findFiles() passes
// bare basenames here, not full paths.
const NOT_SOURCE = /(\.test\.tsx?|\.test-helpers\.ts|^setupTests\.ts)$/;

function definedTokens(): Set<string> {
  const css = readFileSync(TOKENS_FILE, 'utf-8');
  const tokens = new Set<string>();
  for (const [, name] of css.matchAll(/(--[a-zA-Z0-9-]+)\s*:/g)) {
    tokens.add(name);
  }
  return tokens;
}

// Pure function over raw text — no filesystem access — so the regression
// test below can prove the detection logic itself works without needing a
// planted fixture file.
function undefinedVarRefs(source: string, tokens: Set<string>): { name: string; line: number }[] {
  const found: { name: string; line: number }[] = [];
  let match: RegExpExecArray | null;
  const regex = new RegExp(VAR_REFERENCE);

  while ((match = regex.exec(source)) !== null) {
    const name = match[1];
    if (tokens.has(name)) continue;
    const line = source.slice(0, match.index).split('\n').length;
    found.push({ name, line });
  }

  return found;
}

function scanFile(fullPath: string, tokens: Set<string>): string[] {
  const source = readFileSync(fullPath, 'utf-8');
  return undefinedVarRefs(source, tokens).map(
    ({ name, line }) =>
      `${relPath(fullPath)}:${line} — var(${name}) references a custom property ` +
      `not defined in styles/tokens.css; it will silently resolve to its ` +
      `fallback (or nothing) instead of the app's real theme`,
  );
}

function findViolations(): string[] {
  const tokens = definedTokens();
  const sourceFiles = [
    ...findCssFiles(),
    GLOBALS_FILE,
    ...findFiles(SRC_DIR, (name) => /\.tsx?$/.test(name) && !NOT_SOURCE.test(name)),
  ];

  return sourceFiles.flatMap((fullPath) => scanFile(fullPath, tokens));
}

describe('tokens.test.ts', () => {
  it('every var(--x) reference in src/ (CSS Modules, globals.css, .ts/.tsx) resolves to a defined tokens.css property', () => {
    const violations = findViolations();
    expect(violations).toEqual([]);
  });

  it('the detector itself catches an undefined var(--x) reference', () => {
    const tokens = definedTokens();
    const violations = undefinedVarRefs(
      "background: var(--bg-panel);\ncolor: var(--totally-made-up-token-xyz, #fff);",
      tokens,
    );
    expect(violations).toEqual([{ name: '--totally-made-up-token-xyz', line: 2 }]);
  });
});
