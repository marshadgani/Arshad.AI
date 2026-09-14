import { render, screen } from '@testing-library/react';
import { vi } from 'vitest';

import HomeIoT from './HomeIoT';
import Learning from './Learning';
import Travel from './Travel';

// spyOn (not `global.fetch = vi.fn()`, the pattern used elsewhere in this repo)
// so the real fetch implementation is restored after each test rather than
// leaking a stub into later suites that do expect a working fetch.
describe('coming-soon pages never fetch', () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchSpy = vi.spyOn(globalThis, 'fetch') as unknown as ReturnType<typeof vi.fn>;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('HomeIoT', () => {
    it('renders a static coming-soon page without calling fetch', () => {
      render(<HomeIoT />);
      expect(fetchSpy).not.toHaveBeenCalled();
      expect(screen.getByRole('heading', { level: 1, name: 'Home & IoT' })).toBeInTheDocument();
      expect(
        screen.getByText(/Smart-home device integration is on the roadmap/)
      ).toBeInTheDocument();
    });
  });

  describe('Learning', () => {
    it('renders a static coming-soon page without calling fetch', () => {
      render(<Learning />);
      expect(fetchSpy).not.toHaveBeenCalled();
      expect(screen.getByRole('heading', { level: 1, name: 'Learning' })).toBeInTheDocument();
      expect(
        screen.getByText(/Learning provider integrations are planned/)
      ).toBeInTheDocument();
    });
  });

  describe('Travel', () => {
    it('renders a static coming-soon page without calling fetch', () => {
      render(<Travel />);
      expect(fetchSpy).not.toHaveBeenCalled();
      expect(screen.getByRole('heading', { level: 1, name: 'Travel' })).toBeInTheDocument();
      expect(
        screen.getByText(/Travel integrations are planned/)
      ).toBeInTheDocument();
    });
  });
});
