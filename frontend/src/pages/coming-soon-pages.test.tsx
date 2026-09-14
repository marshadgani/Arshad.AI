import { render, screen } from '@testing-library/react';
import { vi } from 'vitest';
import type { MockInstance } from 'vitest';

import ActivityLog from './ActivityLog';
import HomeIoT from './HomeIoT';
import Learning from './Learning';
import Travel from './Travel';

// spyOn (not `global.fetch = vi.fn()`, the pattern used elsewhere in this repo)
// so the real fetch implementation is restored after each test rather than
// leaking a stub into later suites that do expect a working fetch.
describe('coming-soon pages never fetch', () => {
  let fetchSpy: MockInstance;

  beforeEach(() => {
    fetchSpy = vi.spyOn(globalThis, 'fetch');
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('HomeIoT renders a static coming-soon page without calling fetch', () => {
    render(<HomeIoT />);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.getByRole('heading', { level: 1, name: 'Home & IoT' })).toBeInTheDocument();
    expect(screen.getByText(/Smart-home device integration is on the roadmap/)).toBeInTheDocument();
  });

  it('Learning renders a static coming-soon page without calling fetch', () => {
    render(<Learning />);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.getByRole('heading', { level: 1, name: 'Learning' })).toBeInTheDocument();
    expect(screen.getByText(/Learning provider integrations are planned/)).toBeInTheDocument();
  });

  it('Travel renders a static coming-soon page without calling fetch', () => {
    render(<Travel />);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.getByRole('heading', { level: 1, name: 'Travel' })).toBeInTheDocument();
    expect(screen.getByText(/Travel integrations are planned/)).toBeInTheDocument();
  });

  it('ActivityLog renders without fetching and is honest about not recording data', () => {
    render(<ActivityLog />);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.getByRole('heading', { level: 1, name: 'Activity log' })).toBeInTheDocument();
    expect(screen.getByText(/not being captured or stored/)).toBeInTheDocument();
  });
});
