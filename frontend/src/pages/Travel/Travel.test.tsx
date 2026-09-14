import fs from 'fs';
import path from 'path';

import { vi, afterEach, describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import Travel from './Travel';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('Travel page', () => {
  it('never calls fetch', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    render(<Travel />);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('shows the page title', () => {
    render(<Travel />);
    expect(screen.getByRole('heading', { level: 1, name: 'Travel' })).toBeInTheDocument();
  });

  it('shows the reason text', () => {
    render(<Travel />);
    expect(
      screen.getByText(/Travel integrations are planned/)
    ).toBeInTheDocument();
  });

  // Regression guard: this page used to show fabricated Travel dashboard
  // data seeded by backend/scripts/seed_from_mock.py (see mockData.ts
  // 'travel' domain). Relabeling to "Coming soon" is only honest if that
  // fake data never renders again.
  it.each([
    'Miles balance',
    '142,300',
    'BLR',
    'GOA',
    'fare-watcher',
  ])('does not render the fabricated string "%s"', (fabricated) => {
    render(<Travel />);
    expect(screen.queryByText(new RegExp(fabricated.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'))).toBeNull();
  });

  it('renders no interactive button or link elements', () => {
    render(<Travel />);
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByRole('link')).toBeNull();
  });

  // FEAT-140 regression tripwire: confirm the old data-fetching wiring is
  // gone at the source level, not just unobserved at render time.
  it('source does not reference DomainPage or useFetch', () => {
    const source = fs.readFileSync(path.resolve(__dirname, 'Travel.tsx'), 'utf-8');
    expect(source).not.toMatch(/\bDomainPage\b/);
    expect(source).not.toMatch(/\buseFetch\b/);
  });
});
