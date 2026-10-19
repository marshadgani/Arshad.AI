import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import RenderDeployVerdict from './RenderDeployVerdict';

const BODY = {
  verdict: 'regression',
  before_error_count: 2,
  after_error_count: 9,
  before_error_rate: 0.03,
  after_error_rate: 0.15,
  cpu_before_mean: null,
  cpu_after_mean: null,
  memory_before_mean: null,
  memory_after_mean: null,
  latency_before_mean: 120,
  latency_after_mean: 150,
  connected: true,
  needs_reauth: false,
  partial_failures: ['memory'],
  log_truncated: true,
};

function wrap(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

afterEach(() => vi.restoreAllMocks());

describe('RenderDeployVerdict', () => {
  it('prompts when nothing is selected', () => {
    wrap(<RenderDeployVerdict serviceId={null} deployId={null} />);
    expect(screen.getByText(/select a service/i)).toBeInTheDocument();
  });

  it('shows the verdict, only non-null metrics, chips and the truncation note', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: BODY }) }));
    wrap(<RenderDeployVerdict serviceId="srv-a" deployId="dep-1" />);
    expect(await screen.findByText(/verdict: regression/i)).toBeInTheDocument();
    expect(screen.getByRole('rowheader', { name: 'Latency' })).toBeInTheDocument();
    expect(screen.queryByRole('rowheader', { name: 'CPU' })).not.toBeInTheDocument();
    expect(screen.getByText('memory')).toBeInTheDocument();
    expect(screen.getByText(/counts may be understated/i)).toBeInTheDocument();
  });

  it('shows an error state on a failed request', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) }));
    wrap(<RenderDeployVerdict serviceId="srv-a" deployId="dep-1" />);
    expect(await screen.findByRole('alert')).toHaveTextContent(/status 500/);
  });
});
