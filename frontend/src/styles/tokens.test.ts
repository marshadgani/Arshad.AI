import { readFileSync } from 'fs';
import { resolve } from 'path';

import { findCssFiles, relPath, SRC_DIR } from './sourceFiles.test-helpers';

// Guards against the exact bug FEAT-143's gate caught: a CSS Module
// referencing var(--surface, #161b22) where --surface was never defined in
// tokens.css, so the custom property silently and permanently resolved to
// the hardcoded fallback instead of the app's real theme — with no error,
// no lint warning, and every existing test still green. Walks every
// *.module.css file in src/ rather than only the files fixed in that pass,
// so a future CSS Module making the same mistake fails loudly instead of
// shipping an off-palette screen unnoticed. Scoped to CSS Modules only —
// does not cover inline var(--x) in .tsx style props or globals.css.

const TOKENS_FILE = resolve(SRC_DIR, 'styles/tokens.css');

function definedTokens(): Set<string> {
  const css = readFileSync(TOKENS_FILE, 'utf-8');
  const tokens = new Set<string>();
  for (const [, name] of css.matchAll(/(--[a-zA-Z0-9-]+)\s*:/g)) {
    tokens.add(name);
  }
  return tokens;
}

function findViolations(): string[] {
  const tokens = definedTokens();
  const violations: string[] = [];

  for (const fullPath of findCssFiles()) {
    const css = readFileSync(fullPath, 'utf-8');
    const regex = /var\(\s*(--[a-zA-Z0-9-]+)/g;
    let match: RegExpExecArray | null;

    while ((match = regex.exec(css)) !== null) {
      const name = match[1];
      if (tokens.has(name)) continue;

      const precedingText = css.slice(0, match.index);
      const line = precedingText.split('\n').length;
      violations.push(
        `${relPath(fullPath)}:${line} — var(${name}) references a custom property ` +
          `not defined in styles/tokens.css; it will silently resolve to its ` +
          `fallback (or nothing) instead of the app's real theme`,
      );
    }
  }

  return violations;
}

describe('tokens.test.ts', () => {
  it('every var(--x) reference in src/**/*.module.css resolves to a defined tokens.css property', () => {
    const violations = findViolations();
    expect(violations).toEqual([]);
  });
});
