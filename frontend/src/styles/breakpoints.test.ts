import { readFileSync } from 'fs';

import { BREAKPOINTS } from './breakpoints';
import { findCssFiles, relPath } from './sourceFiles.test-helpers';

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

function findViolations(): string[] {
  const violations: string[] = [];

  for (const fullPath of findCssFiles()) {
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
      violations.push(`${relPath(fullPath)}:${line} — @media width ${value}px is not derived from BREAKPOINTS`);
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
