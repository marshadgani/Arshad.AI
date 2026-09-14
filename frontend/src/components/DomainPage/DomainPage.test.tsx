/**
 * FEAT-148 removed the "Open →" and "Configure" buttons — neither had a
 * destination. These tests guard both directions: the buttons stay gone,
 * and the surrounding catalogue content still renders.
 */

import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { DomainConfig } from '../../data/mockData';
import DomainPage from './DomainPage';

vi.mock('../../hooks/useFetch');

import { useFetch } from '../../hooks/useFetch';
import { fetchResult } from '../../hooks/useFetch.test-helpers';

const mockUseFetch = vi.mocked(useFetch);

afterEach(() => {
  vi.restoreAllMocks();
});

function domainFixture(): DomainConfig {
  return {
    slug: 'stocks',
    title: 'Stock Market',
    emoji: '↗',
    tagline: 'Portfolio · watchlist · research',
    kpis: [{ label: 'Portfolio value', value: '₹52.4 L', delta: '+1.2% today' }],
    applications: [
      { id: 'app-live', name: 'Live Portfolio', description: 'Real-time holdings', status: 'live' },
      { id: 'app-beta', name: 'Earnings Calendar', description: 'Upcoming earnings', status: 'beta' },
      { id: 'app-planned', name: 'Options Strategist', description: 'Trade-idea generator', status: 'planned' },
    ],
    agents: [
      {
        name: 'price-watcher',
        description: 'Polls quotes, fires alerts',
        health: 'healthy',
        uptime: '99.95%',
        accuracy: 99,
        lastAction: 'NVDA crossed target',
        lastRun: '1 min ago',
      },
    ],
    feed: [],
  };
}

describe('DomainPage', () => {
  it('shows loading text while the domain is loading', () => {
    mockUseFetch.mockReturnValue(fetchResult({ isLoading: true }));

    render(<DomainPage slug="stocks" />);

    expect(screen.getByText(/Loading stocks/i)).toBeInTheDocument();
  });

  it('shows an error message when the fetch fails', () => {
    mockUseFetch.mockReturnValue(fetchResult({ error: new Error('boom') }));

    render(<DomainPage slug="stocks" />);

    expect(screen.getByText(/Failed to load domain "stocks"/i)).toBeInTheDocument();
    expect(screen.getByText(/boom/i)).toBeInTheDocument();
  });

  it('renders applications and agents with no Open or Configure buttons', () => {
    mockUseFetch.mockReturnValue(fetchResult({ data: domainFixture() }));

    render(<DomainPage slug="stocks" />);

    // Positive assertions — content still renders correctly.
    expect(screen.getByText('Live Portfolio')).toBeInTheDocument();
    expect(screen.getByText('Earnings Calendar')).toBeInTheDocument();
    expect(screen.getByText('Options Strategist')).toBeInTheDocument();
    expect(screen.getByText('price-watcher')).toBeInTheDocument();
    expect(screen.getByText('1 min ago')).toBeInTheDocument();

    // Status pills still resolve for every status, proving the removed
    // ternary did not collapse the 'planned' status tag.
    expect(screen.getByText('live')).toBeInTheDocument();
    expect(screen.getByText('beta')).toBeInTheDocument();
    expect(screen.getByText('planned')).toBeInTheDocument();

    // Narrow negative assertions — the two dead buttons are gone, without
    // banning any future legitimate button (e.g. retry/collapse).
    expect(screen.queryByRole('button', { name: /open/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /configure/i })).toBeNull();
  });
});
