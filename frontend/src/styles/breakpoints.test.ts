import { readFileSync, readdirSync, statSync } from 'fs';
import { resolve } from 'path';

import { BREAKPOINTS } from './breakpoints';

// Guards against JS/CSS desync: a new @media rule added without deriving
// its pixel value from BREAKPOINTS silently reintroduces bugs like the
// off-scale 900px rule this suite caught in Obsidian.module.css. Walks
// every CSS file in src/ rather than only files that already carry a
// marker comment, so an unmarked rule fails loudly instead of passing by
// construction.

const ALLOWED_VALUES = new Set<number>([
  BREAKPOINTS.mobile,
  BREAKPOINTS.tablet,
  BREAKPOINTS.mobile - 0.02,
  BREAKPOINTS.tablet - 0.02,
]);

const EXEMPT_MARKER = /breakpoint-exempt:\s*(.+)/;

function findCssFiles(dir: string): string[] {
  const entries = readdirSync(dir);
  const files: string[] = [];

  for (const entry of entries) {
    const fullPath = resolve(dir, entry);
    const stat = statSync(fullPath);
    if (stat.isDirectory()) {
      files.push(...findCssFiles(fullPath));
    } else if (entry.endsWith('.module.css')) {
      files.push(fullPath);
    }
  }

  return files;
}

function findViolations(): string[] {
  const srcDir = resolve(__dirname, '..');
  const files = findCssFiles(srcDir);
  const violations: string[] = [];

  for (const fullPath of files) {
    const relPath = fullPath.slice(srcDir.length + 1);
    const css = readFileSync(fullPath, 'utf-8');
    const regex = /@media[^{]*\((?:max|min)-width:\s*([\d.]+)px\)[^{]*\{/g;
    let match: RegExpExecArray | null;

    while ((match = regex.exec(css)) !== null) {
      const value = parseFloat(match[1]);
      if (ALLOWED_VALUES.has(value)) continue;

      const precedingText = css.slice(0, match.index);
      const lastLineBreak = precedingText.lastIndexOf('\n');
      const contextStart = Math.max(0, lastLineBreak - 120);
      const context = css.slice(contextStart, match.index);

      if (EXEMPT_MARKER.test(context)) continue;

      const line = precedingText.split('\n').length;
      violations.push(`${relPath}:${line} — @media width ${value}px is not derived from BREAKPOINTS`);
    }
  }

  return violations;
}

describe('breakpoints.test.ts', () => {
  it('every @media px value in src/ is derivable from BREAKPOINTS', () => {
    const violations = findViolations();
    expect(violations).toEqual([]);
  });
});
