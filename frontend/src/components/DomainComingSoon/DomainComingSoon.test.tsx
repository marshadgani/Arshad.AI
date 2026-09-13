import { readFileSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import DomainComingSoon from './DomainComingSoon';

const dirname = path.dirname(fileURLToPath(import.meta.url));

// ─── REQ-140-001/002/003/008 — Component unit tests ─────────────────────────
// DomainComingSoon is a pure presentational component. Every test renders with
// explicit props so test intent is self-documenting; no fixtures or mocks needed.

describe('DomainComingSoon', () => {
  // ── Happy path ─────────────────────────────────────────────────────────────

  it('REQ-140-001/002/003 — renders the title as the page h1 (query by role+name)', () => {
    render(<DomainComingSoon emoji="🏠" title="Home & IoT" reason="No provider connected." />);
    expect(screen.getByRole('heading', { level: 1, name: 'Home & IoT' })).toBeInTheDocument();
  });

  it('REQ-140-001/002/003 — renders the reason text as visible paragraph content', () => {
    render(<DomainComingSoon emoji="🏠" title="Home & IoT" reason="No provider connected." />);
    expect(screen.getByText('No provider connected.')).toBeInTheDocument();
  });

  // ── REQ-140-004 / A11Y-1 — "Coming soon" stays in the accessible text; the
  // decorative "//" prefix is CSS-generated content, not part of the DOM text.
  it('REQ-140-004 — renders the "Coming soon" status text (accessible, not aria-hidden)', () => {
    render(<DomainComingSoon emoji="🏠" title="Home & IoT" reason="No provider connected." />);
    const kicker = screen.getByText('Coming soon');
    expect(kicker).toBeInTheDocument();
    expect(kicker).not.toHaveAttribute('aria-hidden');
  });

  it('REQ-140-008 — marks the decorative emoji span as aria-hidden="true"', () => {
    render(<DomainComingSoon emoji="🏠" title="Home & IoT" reason="No provider connected." />);
    const emoji = screen.getByText('🏠');
    expect(emoji).toHaveAttribute('aria-hidden', 'true');
  });

  // ── REQ-140-008 — No interactive CTA rendered (per SDD: no Connect button) ─
  it('REQ-140-008 — renders no button element (no premature CTA for unbuilt integration)', () => {
    render(<DomainComingSoon emoji="🏠" title="Home & IoT" reason="No provider connected." />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('REQ-140-008 — renders no link element (no premature navigation CTA)', () => {
    render(<DomainComingSoon emoji="🏠" title="Home & IoT" reason="No provider connected." />);
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  // ── A11Y-2 — Section is a named landmark (aria-labelledby -> h1), not an
  // anonymous <section> that assistive tech would not expose as a region.
  it('REQ-140-008 — exposes a "region" landmark named after the page title', () => {
    render(<DomainComingSoon emoji="🏠" title="Home & IoT" reason="No provider connected." />);
    expect(screen.getByRole('region', { name: 'Home & IoT' })).toBeInTheDocument();
  });

  // ── A11Y-2 regression — the h1 id must be instance-unique (useId). With a
  // fixed id, two mounted instances share it and every aria-labelledby resolves
  // to the first h1, so both landmarks report the same (wrong) name.
  it('REQ-140-008 — two instances get distinct landmark names (unique h1 ids)', () => {
    render(
      <>
        <DomainComingSoon emoji="🏠" title="Home & IoT" reason="No provider connected." />
        <DomainComingSoon emoji="✈️" title="Travel" reason="No provider connected." />
      </>
    );
    expect(screen.getByRole('region', { name: 'Home & IoT' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Travel' })).toBeInTheDocument();
  });

  // ── Prop isolation — different domains render their own content correctly ───
  it('REQ-140-002 — Learning props render correct title and reason', () => {
    render(
      <DomainComingSoon
        emoji="📚"
        title="Learning · Second Brain"
        reason="No reading-list provider connected."
      />
    );
    expect(
      screen.getByRole('heading', { level: 1, name: 'Learning · Second Brain' })
    ).toBeInTheDocument();
    expect(screen.getByText('No reading-list provider connected.')).toBeInTheDocument();
  });

  it('REQ-140-003 — Travel props render correct title and reason', () => {
    render(
      <DomainComingSoon
        emoji="✈️"
        title="Travel"
        reason="No flight or hotel provider connected."
      />
    );
    expect(
      screen.getByRole('heading', { level: 1, name: 'Travel' })
    ).toBeInTheDocument();
    expect(screen.getByText('No flight or hotel provider connected.')).toBeInTheDocument();
  });

  // ── Edge case — empty reason string does not crash the component ─────────────
  it('edge case — renders without errors when reason is an empty string', () => {
    expect(() =>
      render(<DomainComingSoon emoji="🏠" title="Test" reason="" />)
    ).not.toThrow();
    expect(screen.getByRole('heading', { level: 1, name: 'Test' })).toBeInTheDocument();
  });

  // ── REQ-140-006 — Reason text must not contain placeholder language ──────────
  // Verified at the component boundary: if a page passes a placeholder string,
  // it must be visible (no swallowing). The content guard lives in the page tests.
  it('REQ-140-006 — reason text is rendered verbatim without alteration', () => {
    const reason = 'No smart-home or device provider is connected.';
    render(<DomainComingSoon emoji="🏠" title="Home & IoT" reason={reason} />);
    expect(screen.getByText(reason)).toBeInTheDocument();
  });
});

// ─── REQ-140-004 — CSS module colour-token guard (frontend.md rule) ───────────
// File-path-coupled (readFileSync): if DomainComingSoon.module.css moves or is
// renamed, update this path. Enforces "no hardcoded hex/rgb/hsl colours" since
// the project has no stylelint; see tasks/backlog.md for the repo-wide follow-up.
describe('DomainComingSoon.module.css — colours come from CSS variables only', () => {
  it('REQ-140-004 — module CSS contains no #hex, rgb(), hsl(), or oklch() colour literals', () => {
    const cssPath = path.resolve(dirname, './DomainComingSoon.module.css');
    const css = readFileSync(cssPath, 'utf-8');
    const hardcodedColour = /#[0-9a-fA-F]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|oklch)\(\s*[\d.]/i;
    expect(css).not.toMatch(hardcodedColour);
  });
});
