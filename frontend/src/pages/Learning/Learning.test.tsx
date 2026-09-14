import fs from 'fs';
import path from 'path';

import { vi, afterEach, describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import Learning from './Learning';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('Learning page', () => {
  it('never calls fetch', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    render(<Learning />);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('shows the page title', () => {
    render(<Learning />);
    expect(screen.getByRole('heading', { level: 1, name: 'Learning' })).toBeInTheDocument();
  });

  it('shows the reason text', () => {
    render(<Learning />);
    expect(
      screen.getByText(/Learning provider integrations are planned/)
    ).toBeInTheDocument();
  });

  // Regression guard: this page used to show fabricated "Second Brain"
  // dashboard data seeded by backend/scripts/seed_from_mock.py (see
  // mockData.ts 'learning' domain). Relabeling to "Coming soon" is only
  // honest if that fake data never renders again.
  it.each([
    'Papers read MTD',
    'Second Brain',
    'goal: 12',
  ])('does not render the fabricated string "%s"', (fabricated) => {
    render(<Learning />);
    expect(screen.queryByText(new RegExp(fabricated.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'))).toBeNull();
  });

  it('renders no interactive button or link elements', () => {
    render(<Learning />);
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByRole('link')).toBeNull();
  });

  // FEAT-140 regression tripwire: confirm the old data-fetching wiring is
  // gone at the source level, not just unobserved at render time.
  it('source does not reference DomainPage or useFetch', () => {
    const source = fs.readFileSync(path.resolve(__dirname, 'Learning.tsx'), 'utf-8');
    expect(source).not.toMatch(/\bDomainPage\b/);
    expect(source).not.toMatch(/\buseFetch\b/);
  });
});
