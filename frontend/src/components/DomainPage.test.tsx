import { render, screen, waitFor } from '@testing-library/react';
import { vi } from 'vitest';

import DomainPage from './DomainPage';

function mockDomain(overrides: Record<string, unknown> = {}) {
  const data = {
    slug: 'finance',
    title: 'Personal Finance',
    emoji: '₹',
    tagline: 't',
    status: 'live',
    kpis: [{ label: 'Linked accounts', value: '2' }],
    applications: [
      { id: 'a', name: 'Budget', description: 'd', status: 'live' },
      { id: 'b', name: 'Planner', description: 'd', status: 'planned' },
    ],
    agents: [],
    feed: [],
    ...overrides,
  };
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ data }),
  }) as unknown as typeof fetch;
}

describe('DomainPage', () => {
  it('shows live KPIs and applications without dead action buttons', async () => {
    mockDomain();
    render(<DomainPage slug="finance" />);
    await waitFor(() => expect(screen.getByText('Budget')).toBeInTheDocument());
    expect(screen.getByText('Linked accounts')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /open/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /configure/i })).not.toBeInTheDocument();
  });

  it('shows no KPI tiles when none are available, rather than invented ones', async () => {
    mockDomain({ kpis: [] });
    render(<DomainPage slug="finance" />);
    await waitFor(() => expect(screen.getByText('Budget')).toBeInTheDocument());
    expect(screen.queryByText('Linked accounts')).not.toBeInTheDocument();
  });
});
