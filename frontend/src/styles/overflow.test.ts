import { readFileSync } from 'fs';
import { resolve } from 'path';

import { SRC_DIR, findCssFiles, findFiles, relPath } from './sourceFiles.test-helpers';

// Static CSS/import guard suite for FEAT-118 (chat de-blocking + responsive
// hardening). Runs at unit-test speed under Vitest's Node environment.
// Node builtins stay in this file and sourceFiles.test-helpers, neither of
// which any browser module imports, so they never enter the client bundle.
//
// This suite proves that specific declarations exist. It does NOT prove
// that nothing overflows at 375px — there is no runtime layout
// verification in this feature (see PR body / tasks/last-gate-report.md
// for the mandatory manual six-viewport checklist).

// ── I1 — no overflow-x:hidden on enumerated layout roots ────────────────
// Enumerated, not inferred: an undefined notion of "layout selector" would
// be unverifiable. Deliberately excludes FundFlowMap.module.css:68
// (overflow-x:auto), which is correct behaviour for a horizontally
// scrollable map, not a bug.
const LAYOUT_ROOT_SELECTORS: Record<string, string[]> = {
  'components/AppLayout.module.css': ['.app', '.main', '.content'],
  'dashboard/Dashboard.module.css': ['.page', '.row'],
  'components/DomainPage.module.css': ['.page', '.section'],
  'chat/ChatPanel.module.css': ['.panel'],
};

function extractSelectorBlock(css: string, selector: string): string | null {
  // Matches ".selector { ... }" or ".selector," (comma-joined) — first
  // brace-delimited block whose selector list contains the exact class.
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = new RegExp(`(^|[\\s,}])${escaped}(?=[\\s,.:{])[^{]*\\{([^}]*)\\}`, 'm');
  const match = pattern.exec(css);
  return match ? match[2] : null;
}

function findI1Violations(): string[] {
  const violations: string[] = [];

  for (const [file, selectors] of Object.entries(LAYOUT_ROOT_SELECTORS)) {
    const fullPath = resolve(SRC_DIR, file);
    const css = readFileSync(fullPath, 'utf-8');

    for (const selector of selectors) {
      const block = extractSelectorBlock(css, selector);
      if (block && /overflow-x\s*:\s*hidden/.test(block)) {
        violations.push(`${file} ${selector} declares overflow-x:hidden`);
      }
    }
  }

  return violations;
}

// ── I2 — every vh declaration is immediately followed by its dvh twin ───
// Per-declaration, not per-file: a per-file "contains dvh somewhere" check
// would pass with only one of two sites fixed (Obsidian had two). Anchored
// on a digit boundary so "100dvh" itself can never satisfy the vh match.
const VH_DECLARATION = /(?<=[\d.])vh\b/;

function findI2Violations(): string[] {
  const violations: string[] = [];

  for (const fullPath of findCssFiles()) {
    const css = readFileSync(fullPath, 'utf-8');
    const lines = css.split('\n');

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (!VH_DECLARATION.test(line)) continue;

      // Find next non-blank line.
      let j = i + 1;
      while (j < lines.length && lines[j].trim() === '') j++;
      const next = j < lines.length ? lines[j] : '';
      const expected = line.replace(/([\d.]+)vh\b/g, '$1dvh');

      if (next.trim() !== expected.trim()) {
        violations.push(`${relPath(fullPath)}:${i + 1} — vh declaration has no matching dvh line immediately after it`);
      }
    }
  }

  return violations;
}

// ── I3 — named 1fr-track text children carry min-width:0 ────────────────
// Per-selector block parse, not per-file. .row2 is intentionally absent —
// it was deleted, not hardened.
const MIN_WIDTH_ZERO_TARGETS: Record<string, string[]> = {
  'dashboard/Dashboard.module.css': ['.rowText', '.tickMsg', '.notifBody', '.notifTitle', '.notifDetail', '.eventTitle'],
  'components/DomainPage.module.css': ['.agentName', '.appName', '.appDesc', '.feedMsg'],
};

function findI3Violations(): string[] {
  const violations: string[] = [];

  for (const [file, selectors] of Object.entries(MIN_WIDTH_ZERO_TARGETS)) {
    const fullPath = resolve(SRC_DIR, file);
    const css = readFileSync(fullPath, 'utf-8');

    for (const selector of selectors) {
      const block = extractSelectorBlock(css, selector);
      if (!block) {
        violations.push(`${file} ${selector} — selector not found`);
        continue;
      }
      if (!/min-width\s*:\s*0/.test(block)) {
        violations.push(`${file} ${selector} — missing min-width:0`);
      }
    }
  }

  return violations;
}

// ── I4 — chat module import boundary (REQ-118-03) ────────────────────────
const CHAT_ALLOWED_PREFIXES = ['chat/', 'pages/Chat.tsx'];
const CHAT_IMPORT_NAMES = ['useChatStream', 'createChatSession'];

function findI4Violations(): string[] {
  const tsFiles = findFiles(SRC_DIR, (name) => name.endsWith('.ts') || name.endsWith('.tsx'));
  const violations: string[] = [];

  for (const fullPath of tsFiles) {
    const rel = relPath(fullPath);
    if (CHAT_ALLOWED_PREFIXES.some((prefix) => rel.startsWith(prefix))) continue;

    const content = readFileSync(fullPath, 'utf-8');
    for (const name of CHAT_IMPORT_NAMES) {
      const importPattern = new RegExp(`import[^;]*\\b${name}\\b[^;]*from`);
      if (importPattern.test(content)) {
        violations.push(`${rel} imports ${name} outside the chat module boundary`);
      }
    }
  }

  return violations;
}

describe('overflow.test.ts', () => {
  it('I1: no overflow-x:hidden on enumerated layout roots', () => {
    expect(findI1Violations()).toEqual([]);
  });

  it('I2: every vh declaration is immediately followed by its dvh twin', () => {
    expect(findI2Violations()).toEqual([]);
  });

  it('I3: named 1fr-track text children carry min-width:0', () => {
    expect(findI3Violations()).toEqual([]);
  });

  it('I4: useChatStream/createChatSession are only imported inside the chat module boundary', () => {
    expect(findI4Violations()).toEqual([]);
  });
});
