import fs from 'fs';
import path from 'path';

import { vi, afterEach, describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import HomeIoT from './HomeIoT';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('HomeIoT page', () => {
  it('never calls fetch', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    render(<HomeIoT />);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('shows the page title', () => {
    render(<HomeIoT />);
    expect(screen.getByRole('heading', { level: 1, name: 'Home & IoT' })).toBeInTheDocument();
  });

  it('shows the reason text', () => {
    render(<HomeIoT />);
    expect(
      screen.getByText(/Smart-home device integration is on the roadmap/)
    ).toBeInTheDocument();
  });

  // Regression guard: this page used to show fabricated Home & IoT dashboard
  // data seeded by backend/scripts/seed_from_mock.py (see mockData.ts 'home'
  // domain). Relabeling to "Coming soon" is only honest if that fake data
  // never renders again.
  it.each([
    'Devices online',
    'Alerts open',
    'Fridge door',
    '14 / 16',
    'anomaly-watcher',
  ])('does not render the fabricated string "%s"', (fabricated) => {
    render(<HomeIoT />);
    expect(screen.queryByText(new RegExp(fabricated.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'))).toBeNull();
  });

  it('renders no interactive button or link elements', () => {
    render(<HomeIoT />);
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByRole('link')).toBeNull();
  });

  // FEAT-140 regression tripwire: FEAT-140 halted before this file was ever
  // edited, leaving the old data-fetching DomainPage wiring in place. Confirm
  // the fetching pattern is gone at the source level, not just unobserved at
  // render time.
  it('source does not reference DomainPage or useFetch', () => {
    const source = fs.readFileSync(path.resolve(__dirname, 'HomeIoT.tsx'), 'utf-8');
    expect(source).not.toMatch(/\bDomainPage\b/);
    expect(source).not.toMatch(/\buseFetch\b/);
  });
});
