/**
 * DomainPage — behaviour tests.
 *
 * Pins the component's real logic (loading/error branches, header, KPIs,
 * application and agent cards, activity feed, children slot). The final
 * case guards against the dead "Open →" / "Configure" buttons that were
 * removed by FEAT-UNDEFINED-001 quietly reappearing.
 */

import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import DomainPage from './DomainPage';
import type { DomainConfig } from '../data/mockData';

vi.mock('../hooks/useFetch');

import { useFetch } from '../hooks/useFetch';

const mockUseFetch = vi.mocked(useFetch);

const fixture: DomainConfig = {
  slug: 'finance',
  title: 'Personal Finance',
  emoji: '$',
  tagline: 'Net worth · cash flow · investments',
  kpis: [
    { label: 'Net worth', value: '₹1.42 Cr', delta: '+2.1% MoM' },
    { label: 'Monthly spend', value: '₹68,420' },
  ],
  applications: [
    { id: 'a1', name: 'Expense Logger', description: 'Tracks spend', status: 'live' },
    { id: 'a2', name: 'Portfolio Tracker', description: 'Tracks investments', status: 'beta' },
    { id: 'a3', name: 'Tax Planner', description: 'Plans taxes', status: 'planned' },
  ],
  agents: [
    {
      name: 'budget-agent',
      description: 'Monitors budget thresholds',
      health: 'healthy',
      uptime: '99.9%',
      accuracy: 97,
      lastAction: 'Flagged overspend',
      lastRun: '2 min ago',
    },
    {
      name: 'forecast-agent',
      description: 'Forecasts cash flow',
      health: 'degraded',
      uptime: '92.1%',
      accuracy: 81,
      lastAction: 'Retrying data pull',
      lastRun: '10 min ago',
    },
  ],
  feed: [{ id: 'f1', message: 'Synced 3 accounts', time: '09:00' }],
};

beforeEach(() => {
  mockUseFetch.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('DomainPage', () => {
  it('shows a loading message while the domain is loading', () => {
    mockUseFetch.mockReturnValue({ data: null, isLoading: true, error: null, refetch: vi.fn() });

    render(<DomainPage slug="finance" />);

    expect(screen.getByText(/Loading finance/)).toBeInTheDocument();
    expect(screen.queryByText('Applications')).not.toBeInTheDocument();
  });

  it('shows the slug and error message on fetch failure', () => {
    mockUseFetch.mockReturnValue({ data: null, isLoading: false, error: new Error('boom'), refetch: vi.fn() });

    render(<DomainPage slug="finance" />);

    expect(screen.getByText(/finance/)).toBeInTheDocument();
    expect(screen.getByText(/boom/)).toBeInTheDocument();
  });

  it('renders the header, tagline and KPIs', () => {
    mockUseFetch.mockReturnValue({ data: fixture, isLoading: false, error: null, refetch: vi.fn() });

    render(<DomainPage slug="finance" />);

    expect(screen.getByRole('heading', { name: 'Personal Finance' })).toBeInTheDocument();
    expect(screen.getByText(fixture.tagline)).toBeInTheDocument();
    expect(screen.getByText('Net worth')).toBeInTheDocument();
    expect(screen.getByText('₹1.42 Cr')).toBeInTheDocument();
    expect(screen.getByText('+2.1% MoM')).toBeInTheDocument();
    expect(screen.getByText('Monthly spend')).toBeInTheDocument();
    expect(screen.getByText('₹68,420')).toBeInTheDocument();
  });

  it('renders application cards with name, description and status for every status', () => {
    mockUseFetch.mockReturnValue({ data: fixture, isLoading: false, error: null, refetch: vi.fn() });

    render(<DomainPage slug="finance" />);

    expect(screen.getByText('Expense Logger')).toBeInTheDocument();
    expect(screen.getByText('Portfolio Tracker')).toBeInTheDocument();
    expect(screen.getByText('Tax Planner')).toBeInTheDocument();
    expect(screen.getByText('live')).toBeInTheDocument();
    expect(screen.getByText('beta')).toBeInTheDocument();
    expect(screen.getByText('planned')).toBeInTheDocument();
  });

  it('renders agent cards with name, uptime, accuracy and last run', () => {
    mockUseFetch.mockReturnValue({ data: fixture, isLoading: false, error: null, refetch: vi.fn() });

    render(<DomainPage slug="finance" />);

    expect(screen.getByText('budget-agent')).toBeInTheDocument();
    expect(screen.getByText('99.9%')).toBeInTheDocument();
    expect(screen.getByText('97%')).toBeInTheDocument();
    expect(screen.getByText('↳ Flagged overspend')).toBeInTheDocument();
    expect(screen.getByText('2 min ago')).toBeInTheDocument();
    expect(screen.getByText('forecast-agent')).toBeInTheDocument();
  });

  it('renders the activity feed and any children passed to it', () => {
    mockUseFetch.mockReturnValue({ data: fixture, isLoading: false, error: null, refetch: vi.fn() });

    render(
      <DomainPage slug="finance">
        <div>child marker</div>
      </DomainPage>,
    );

    expect(screen.getByText('09:00')).toBeInTheDocument();
    expect(screen.getByText('Synced 3 accounts')).toBeInTheDocument();
    expect(screen.getByText('child marker')).toBeInTheDocument();
  });

  // Placeholder guard: DomainPage intentionally has no interactive controls
  // today — the "Open →" and "Configure" buttons were removed because no
  // per-application or per-agent destination exists (see
  // tasks/alternate-features.md / the backlog entry filed alongside this
  // change). DELETE this case when a real destination is implemented; it is
  // not a requirement that the page stay button-free forever.
  it('has no dead interactive controls', () => {
    mockUseFetch.mockReturnValue({ data: fixture, isLoading: false, error: null, refetch: vi.fn() });

    render(<DomainPage slug="finance" />);

    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
