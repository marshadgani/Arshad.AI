import { act, render, screen, waitFor } from '@testing-library/react';
import { vi } from 'vitest';

import DomainPage from './DomainPage';
import type { DomainConfig } from '../../data/mockData';

const domainFixture: DomainConfig = {
  slug: 'finance',
  title: 'Personal Finance',
  tagline: 'Track spend, budgets, and net worth',
  emoji: '💰',
  kpis: [{ label: 'Net worth', value: '$42,000', delta: '+3.2%' }],
  applications: [
    {
      id: 'app-1',
      name: 'Expense Logger',
      description: 'Captures and categorises transactions',
      status: 'live',
    },
  ],
  agents: [
    {
      name: 'Transaction Tagger',
      description: 'Auto-labels transactions by category',
      health: 'healthy',
      uptime: '99.9%',
      accuracy: 97,
      lastAction: 'Tagged 12 transactions',
      lastRun: '2 min ago',
    },
  ],
  feed: [{ id: 'feed-1', time: '09:00', message: 'Synced accounts' }],
};

/** Covers every Application.status and AgentHealth variant, not just the defaults. */
const multiVariantFixture: DomainConfig = {
  ...domainFixture,
  applications: [
    { id: 'a1', name: 'Live App', description: 'live desc', status: 'live' },
    { id: 'a2', name: 'Beta App', description: 'beta desc', status: 'beta' },
    { id: 'a3', name: 'Planned App', description: 'planned desc', status: 'planned' },
  ],
  agents: [
    {
      name: 'Healthy Agent',
      description: 'ok',
      health: 'healthy',
      uptime: '99%',
      accuracy: 90,
      lastAction: 'ran',
      lastRun: '1 min ago',
    },
    {
      name: 'Degraded Agent',
      description: 'slow',
      health: 'degraded',
      uptime: '80%',
      accuracy: 60,
      lastAction: 'ran slow',
      lastRun: '2 hr ago',
    },
    {
      name: 'Offline Agent',
      description: 'down',
      health: 'offline',
      uptime: '0%',
      accuracy: 0,
      lastAction: 'failed',
      lastRun: '5 hr ago',
    },
    {
      name: 'Training Agent',
      description: 'learning',
      health: 'training',
      uptime: '—',
      accuracy: 0,
      lastAction: 'training run',
      lastRun: 'now',
    },
  ],
};

/** Domain with zero applications, agents and feed items — the empty-state edge case. */
const emptyDomainFixture: DomainConfig = {
  ...domainFixture,
  applications: [],
  agents: [],
  feed: [],
};

function mockFetchOnce(body: unknown) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => body,
  }) as unknown as typeof fetch;
}

describe('DomainPage', () => {
  it("renders each application's name, description and status tag", async () => {
    mockFetchOnce({ data: domainFixture });
    render(<DomainPage slug="finance" />);

    expect(await screen.findByText('Expense Logger')).toBeInTheDocument();
    expect(screen.getByText('Captures and categorises transactions')).toBeInTheDocument();
    expect(screen.getByText('live')).toBeInTheDocument();
  });

  it('does not render a dead Open button — deliberately removed, no per-application route exists', async () => {
    mockFetchOnce({ data: domainFixture });
    render(<DomainPage slug="finance" />);

    await screen.findByText('Expense Logger');
    expect(screen.queryByRole('button', { name: /open/i })).not.toBeInTheDocument();
  });

  it("renders each agent's name, uptime, accuracy, last action and last run", async () => {
    mockFetchOnce({ data: domainFixture });
    render(<DomainPage slug="finance" />);

    expect(await screen.findByText('Transaction Tagger')).toBeInTheDocument();
    expect(screen.getByText('99.9%')).toBeInTheDocument();
    expect(screen.getByText('97%')).toBeInTheDocument();
    expect(screen.getByText('↳ Tagged 12 transactions')).toBeInTheDocument();
    expect(screen.getByText('2 min ago')).toBeInTheDocument();
  });

  it('does not render a dead Configure button — deliberately removed, no agent config endpoint exists', async () => {
    mockFetchOnce({ data: domainFixture });
    render(<DomainPage slug="finance" />);

    await screen.findByText('Transaction Tagger');
    expect(screen.queryByRole('button', { name: /configure/i })).not.toBeInTheDocument();
  });

  it('shows the loading state until the request resolves', async () => {
    let resolveFetch!: (value: unknown) => void;
    const pending = new Promise((resolve) => {
      resolveFetch = resolve;
    });
    global.fetch = vi.fn().mockReturnValue(pending) as unknown as typeof fetch;

    render(<DomainPage slug="finance" />);

    expect(screen.getByText(/Loading finance/i)).toBeInTheDocument();

    await act(async () => {
      resolveFetch({
        ok: true,
        status: 200,
        json: async () => ({ data: domainFixture }),
      });
      await pending;
    });

    expect(await screen.findByText('Expense Logger')).toBeInTheDocument();
  });

  it('shows the error message when the request fails', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      text: async () => 'boom',
    }) as unknown as typeof fetch;

    const { container } = render(<DomainPage slug="finance" />);

    await act(async () => {
      await Promise.resolve();
    });

    expect(container.textContent).toContain('Failed to load domain "finance": 500 Internal Server Error: boom');
  });

  it('shows the error message when the request rejects with a network error (not just a non-ok response)', async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch')) as unknown as typeof fetch;

    const { container } = render(<DomainPage slug="finance" />);

    await act(async () => {
      await Promise.resolve();
    });

    expect(container.textContent).toContain('Failed to load domain "finance"');
    expect(container.textContent).toContain('Failed to fetch');
  });

  it('requests the domain-specific endpoint for the given slug, not a hardcoded one', async () => {
    mockFetchOnce({ data: { ...domainFixture, slug: 'github' } });

    render(<DomainPage slug="github" />);
    await screen.findByText('Expense Logger');

    expect(global.fetch).toHaveBeenCalledWith(
      '/api/v1/domains/github',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it('does not render Open or Configure buttons across every Application.status and AgentHealth variant', async () => {
    mockFetchOnce({ data: multiVariantFixture });
    render(<DomainPage slug="finance" />);

    expect(await screen.findByText('Live App')).toBeInTheDocument();
    expect(screen.getByText('Beta App')).toBeInTheDocument();
    expect(screen.getByText('Planned App')).toBeInTheDocument();
    expect(screen.getByText('Healthy Agent')).toBeInTheDocument();
    expect(screen.getByText('Degraded Agent')).toBeInTheDocument();
    expect(screen.getByText('Offline Agent')).toBeInTheDocument();
    expect(screen.getByText('Training Agent')).toBeInTheDocument();

    expect(screen.queryByRole('button', { name: /open/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /configure/i })).not.toBeInTheDocument();
  });

  it('renders "0 total" / "0 active" and no items when a domain has no applications or agents', async () => {
    mockFetchOnce({ data: emptyDomainFixture });
    const { container } = render(<DomainPage slug="finance" />);

    await waitFor(() => expect(container.textContent).toContain('0 total'));
    expect(container.textContent).toContain('0 active');
    expect(screen.queryByText('Expense Logger')).not.toBeInTheDocument();
    expect(screen.queryByText('Transaction Tagger')).not.toBeInTheDocument();
  });
});
