import { readFileSync } from 'fs';
import { resolve } from 'path';

import { findCssFiles, findFiles, relPath, SRC_DIR } from './sourceFiles.test-helpers';

// Guards against the exact bug FEAT-143's gate caught: a CSS Module
// referencing var(--surface, #161b22) where --surface was never defined in
// tokens.css, so the custom property silently and permanently resolved to
// the hardcoded fallback instead of the app's real theme — with no error,
// no lint warning, and every existing test still green. Walks every
// *.module.css file, globals.css, tokens.css itself, and every .ts/.tsx
// source in src/ (FEAT-144 shipped this scoped to *.module.css only;
// FEAT-160 widened it after gate agents found inline var(--x) in .tsx style
// props, tokens.css's own body{} rule, and healthFormat.ts were unguarded)
// so a future reference to an undefined token — wherever it's written —
// fails loudly instead of shipping unnoticed. Comments are stripped before
// matching so a var(--x) or --x: mentioned only in prose doesn't count as
// real usage or a real definition — this is a plain-text guard, not a full
// CSS parser, so a malformed comment that corrupts real CSS syntax (as
// FEAT-160's own tokens.css edit briefly did — a stray */ inside a comment
// terminated it early) can still slip past; always confirm with a real
// build after touching tokens.css.

const TOKENS_FILE = resolve(SRC_DIR, 'styles/tokens.css');
const GLOBALS_FILE = resolve(SRC_DIR, 'styles/globals.css');
const VAR_REFERENCE = /var\(\s*(--[a-zA-Z0-9-]+)/g;
const CSS_COMMENT = /\/\*[\s\S]*?\*\//g;

// Excludes test files (and their shared helpers) so this suite's own
// fixture below — a deliberately undefined var(--x) used to prove the
// detector works — isn't also picked up as a second, unrelated violation
// when this file itself gets walked as a .ts source. findFiles() passes
// bare basenames here, not full paths.
const NOT_SOURCE = /(\.test\.tsx?|\.test-helpers\.ts|^setupTests\.ts)$/;

function definedTokens(): Set<string> {
  const css = readFileSync(TOKENS_FILE, 'utf-8').replace(CSS_COMMENT, '');
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
  const stripped = source.replace(CSS_COMMENT, (comment) => comment.replace(/[^\n]/g, ' '));
  const found: { name: string; line: number }[] = [];
  let match: RegExpExecArray | null;
  const regex = new RegExp(VAR_REFERENCE);

  while ((match = regex.exec(stripped)) !== null) {
    const name = match[1];
    if (tokens.has(name)) continue;
    const line = stripped.slice(0, match.index).split('\n').length;
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
    TOKENS_FILE,
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

  // A guard's own regex is not a CSS parser: it caught the undefined-token
  // class of bug fine, but a stray */ inside a comment (a real incident —
  // "--accent-*/" in an earlier draft of this file's own tokens.css edit)
  // corrupts CSS syntax in a way plain-text matching can't detect at all.
  // This check can't tell whether a comment is well-formed either, but it
  // can catch the specific, cheap-to-verify symptom: an unequal count of
  // comment openers and closers, which a properly paired (non-nesting)
  // set of CSS comments always has equal.
  it('tokens.css has a matching number of comment openers and closers', () => {
    const css = readFileSync(TOKENS_FILE, 'utf-8');
    const opens = css.match(/\/\*/g)?.length ?? 0;
    const closes = css.match(/\*\//g)?.length ?? 0;
    expect(closes).toBe(opens);
  });
});
