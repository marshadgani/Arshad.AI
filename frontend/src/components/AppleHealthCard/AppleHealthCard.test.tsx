import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { AppleHealthSnapshot, UseAppleHealthResult } from '../../hooks/useAppleHealth';
import AppleHealthCard from './AppleHealthCard';

function makeResult(overrides: Partial<UseAppleHealthResult> = {}): UseAppleHealthResult {
  return {
    data: null,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  };
}

function snapshot(overrides: Partial<AppleHealthSnapshot> = {}): AppleHealthSnapshot {
  return {
    connected: false,
    stale: false,
    resting_heart_rate: null,
    heart_rate_variability_ms: null,
    sleep_hours: null,
    active_energy_kcal: null,
    steps: null,
    vo2_max: null,
    recorded_at: null,
    received_at: null,
    ...overrides,
  };
}

describe('AppleHealthCard', () => {
  it('renders the loading skeleton', () => {
    render(<AppleHealthCard useHook={() => makeResult({ isLoading: true })} />);
    expect(screen.getByLabelText(/loading apple health data/i)).toBeInTheDocument();
  });

  it('renders the error state with a working retry button', async () => {
    const refetch = vi.fn();
    render(
      <AppleHealthCard
        useHook={() => makeResult({ error: new Error('boom'), refetch })}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent(/couldn.t reach/i);
    await userEvent.click(screen.getByRole('button', { name: /retry/i }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it('renders the not-connected empty state with a connect CTA', () => {
    render(
      <AppleHealthCard useHook={() => makeResult({ data: snapshot({ connected: false }) })} />,
    );
    expect(
      screen.getByRole('button', { name: /connect apple health/i }),
    ).toBeInTheDocument();
  });

  it('renders a stale-sync warning when connected but no recent push', () => {
    render(
      <AppleHealthCard
        useHook={() => makeResult({ data: snapshot({ connected: true, stale: true }) })}
      />,
    );
    expect(screen.getByRole('status')).toHaveTextContent(/sync has gone quiet/i);
    expect(screen.getByRole('button', { name: /reissue sync token/i })).toBeInTheDocument();
  });

  it('renders live metrics when connected with data', () => {
    render(
      <AppleHealthCard
        useHook={() =>
          makeResult({
            data: snapshot({
              connected: true,
              resting_heart_rate: 52,
              steps: 8421,
              received_at: new Date().toISOString(),
            }),
          })
        }
      />,
    );
    expect(screen.getByText('52 bpm')).toBeInTheDocument();
    expect(screen.getByText('8,421')).toBeInTheDocument();
  });

  it('walks the connect flow and reveals the one-time ingest token', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        data: { integration_id: 'abc', redirect_url: null, ingest_token: 'secret-token-123' },
      }),
    }) as unknown as typeof fetch;

    render(
      <AppleHealthCard useHook={() => makeResult({ data: snapshot({ connected: false }) })} />,
    );

    await userEvent.click(screen.getByRole('button', { name: /connect apple health/i }));
    await userEvent.click(screen.getByRole('button', { name: /generate token/i }));

    await waitFor(() => {
      expect(screen.getByText('secret-token-123')).toBeInTheDocument();
    });
    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/integrations/apple_health/connect',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('shows a modal error when the connect request fails', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ error: { message: 'upstream failed' } }),
    }) as unknown as typeof fetch;

    render(
      <AppleHealthCard useHook={() => makeResult({ data: snapshot({ connected: false }) })} />,
    );

    await userEvent.click(screen.getByRole('button', { name: /connect apple health/i }));
    await userEvent.click(screen.getByRole('button', { name: /generate token/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/upstream failed/i);
    });
  });
});
