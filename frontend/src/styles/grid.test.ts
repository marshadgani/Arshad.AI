import { readFileSync } from 'fs';

import { findCssFiles, relPath } from './sourceFiles.test-helpers';

// Guards the boundary introduced when the responsive column ladder was
// extracted into grid.module.css.
//
// Before the extraction, Dashboard and DomainPage each carried their own
// @media blocks restating the same collapse sequence, and they had already
// drifted (identical four-up grids collapsed to different counts on
// mobile). Composing from one module fixes today's drift; this test stops
// tomorrow's, because a stylesheet that re-declares columns at a breakpoint
// has silently re-forked the ladder and nothing else would notice.
//
// Not every such declaration is a fork — a two-track page header collapsing
// to one column is a layout concern local to that header, not a card grid.
// Those carry an explicit `grid-exempt:` marker, matching the exemption
// convention breakpoints.test.ts already uses, so the escape hatch is
// deliberate and reviewable rather than assumed.

const LADDER_OWNER = 'styles/grid.module.css';
const EXEMPT_MARKER = /grid-exempt:\s*(.+)/;

// Returns the [start, end) character offsets of every width-conditioned
// @media block, matching braces so a nested block cannot end the range early.
function widthMediaBlocks(css: string): Array<[number, number]> {
  const blocks: Array<[number, number]> = [];
  const opener = /@media[^{]*\((?:max|min)-width:[^{]*\{/g;
  let match: RegExpExecArray | null;

  while ((match = opener.exec(css)) !== null) {
    let depth = 1;
    let i = opener.lastIndex;
    while (i < css.length && depth > 0) {
      if (css[i] === '{') depth++;
      else if (css[i] === '}') depth--;
      i++;
    }
    blocks.push([match.index, i]);
  }

  return blocks;
}

function findViolations(): string[] {
  const violations: string[] = [];

  for (const fullPath of findCssFiles()) {
    const rel = relPath(fullPath);
    if (rel === LADDER_OWNER) continue;

    const css = readFileSync(fullPath, 'utf-8');

    for (const [start, end] of widthMediaBlocks(css)) {
      const block = css.slice(start, end);
      const declaration = /grid-template-columns/g;
      let hit: RegExpExecArray | null;

      while ((hit = declaration.exec(block)) !== null) {
        // Look back over the preceding rule for an exemption marker.
        const before = block.slice(0, hit.index);
        const ruleStart = Math.max(before.lastIndexOf('}'), before.lastIndexOf('{'));
        const context = block.slice(Math.max(0, ruleStart - 200), hit.index);
        if (EXEMPT_MARKER.test(context)) continue;

        const line = css.slice(0, start + hit.index).split('\n').length;
        violations.push(
          `${rel}:${line} — grid-template-columns inside a width media query; ` +
            `compose a ladder from ${LADDER_OWNER} or add a "grid-exempt:" marker`,
        );
      }
    }
  }

  return violations;
}

describe('grid.test.ts', () => {
  it('the responsive column ladder is declared only in grid.module.css', () => {
    expect(findViolations()).toEqual([]);
  });
});
