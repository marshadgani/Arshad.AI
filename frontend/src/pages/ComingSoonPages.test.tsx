import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import HomeIoT from './HomeIoT';
import Learning from './Learning';
import Travel from './Travel';
import { COMING_SOON_DOMAINS } from '../data/comingSoonDomains';

const pages = [
  { name: 'HomeIoT', Component: HomeIoT, slug: 'home-iot' as const },
  { name: 'Learning', Component: Learning, slug: 'learning' as const },
  { name: 'Travel', Component: Travel, slug: 'travel' as const },
];

// ─── REQ-140-001/002/003/005/006/007 — Page integration tests ────────────────
// The runtime fetch spy (T2) is the load-bearing regression guard for the
// zero-network-I/O contract: it is strictly stronger than a static source-grep
// for "DomainPage"/"useFetch" (which only catches an import, not a call, and
// silently stops guarding if a file is renamed). No source-grep tests here —
// see SDD testing_architecture for the rationale.
describe('coming-soon domain pages', () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  for (const { name, Component, slug } of pages) {
    it(`REQ-140-001/002/003 — ${name} renders its h1 heading sourced from COMING_SOON_DOMAINS`, () => {
      render(<Component />);
      const { title } = COMING_SOON_DOMAINS[slug];
      expect(screen.getByRole('heading', { level: 1, name: title })).toBeInTheDocument();
    });

    it(`REQ-140-006 — ${name} renders the exact reason string from COMING_SOON_DOMAINS`, () => {
      render(<Component />);
      const { reason } = COMING_SOON_DOMAINS[slug];
      expect(screen.getByText(reason)).toBeInTheDocument();
    });

    // ── A11Y-1 — "Coming soon" must be present in the accessible text, not
    // hidden — it is the only status marker a screen-reader user gets.
    it(`REQ-140-008 — ${name} exposes "Coming soon" in the accessible text`, () => {
      render(<Component />);
      expect(screen.getByText('Coming soon')).toBeInTheDocument();
    });
  }

  // ── REQ-140-005 — Zero-network-I/O contract, covering all three pages ────────
  it('REQ-140-005 — none of the three pages makes any fetch call on mount', () => {
    for (const { Component } of pages) {
      render(<Component />);
    }
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  // ── REQ-140-007 — Components export a valid React component (route still works)
  it('REQ-140-007 — all three page components render without throwing (routes remain navigable)', () => {
    for (const { Component } of pages) {
      expect(() => render(<Component />)).not.toThrow();
    }
  });
});

// ─── REQ-140-006 — COMING_SOON_DOMAINS data-map structural completeness ───────
describe('COMING_SOON_DOMAINS data map', () => {
  const requiredSlugs = ['home-iot', 'learning', 'travel'] as const;
  // Unanchored so a reason string that merely *contains* placeholder language
  // (not just one that equals it exactly) is also caught.
  const placeholderPattern = /\b(tbd|todo|placeholder|lorem)\b/i;

  it('REQ-140-006 — contains a non-placeholder emoji/title/reason entry for every required slug', () => {
    for (const slug of requiredSlugs) {
      expect(COMING_SOON_DOMAINS).toHaveProperty(slug);
      const { emoji, title, reason } = COMING_SOON_DOMAINS[slug];
      expect(emoji.trim().length).toBeGreaterThan(0);
      expect(title.trim().length).toBeGreaterThan(0);
      expect(reason.trim().length).toBeGreaterThan(10);
      expect(reason).not.toMatch(placeholderPattern);
    }
  });

  // ── INV-3 — `satisfies Record<string, DomainComingSoonProps>` keeps keys
  // literal ('home-iot' | 'learning' | 'travel'), so a typo'd lookup is a
  // compile error, not an `undefined` spread at runtime. If this stopped
  // compiling as `@ts-expect-error`, someone changed the map back to a ':'
  // annotation — see SDD INV-3.
  it('INV-3 — a typo\'d domain key fails to type-check (compile-time only, no runtime assertion)', () => {
    // @ts-expect-error 'home-io' is not a key of COMING_SOON_DOMAINS
    const typoLookup = COMING_SOON_DOMAINS['home-io'];
    expect(typoLookup).toBeUndefined();
  });
});
