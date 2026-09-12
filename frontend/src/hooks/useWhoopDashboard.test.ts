/**
 * useWhoopDashboard — secondary-fetch skip propagation.
 *
 * The hook's load-bearing behaviour is negative: while Whoop is
 * disconnected or needs re-authentication, /hrv-trend and /workouts are
 * guaranteed to 404/409, so they must not be requested at all. Asserting
 * that means asserting on calls that did NOT happen, which nothing else
 * in the suite does — a regression here is invisible in the UI (the cards
 * render an empty state either way) and only shows up as pointless 4xx
 * traffic and a spurious error banner.
 */

import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useWhoopDashboard } from './useWhoopDashboard';

const DASHBOARD_URL = '/api/v1/whoop/dashboard';
const HRV_URL = '/api/v1/whoop/hrv-trend';
const WORKOUTS_URL = '/api/v1/whoop/workouts';

type RouteResponse = { status?: number; body?: unknown };

function ok(body: unknown): RouteResponse {
  return { status: 200, body };
}

/**
 * Routes fetch by URL substring. Any URL with no configured route rejects,
 * so an unexpected request fails the test loudly instead of silently
 * resolving to a default.
 */
function mockFetch(routes: Record<string, RouteResponse>) {
  const fetchMock = vi.fn(async (url: string) => {
    const key = Object.keys(routes).find((r) => url.includes(r));
    if (!key) throw new Error(`Unexpected fetch: ${url}`);
    const { status = 200, body } = routes[key];
    return {
      ok: status >= 200 && status < 300,
      status,
      statusText: String(status),
      json: async () => body,
      text: async () => JSON.stringify(body),
    } as Response;
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

function calledUrls(fetchMock: ReturnType<typeof vi.fn>): string[] {
  return fetchMock.mock.calls.map((call) => String(call[0]));
}

function dashboardBody(overrides: Record<string, unknown> = {}) {
  return {
    data: {
      connected: true,
      needs_reauth: false,
      degraded: false,
      recovery: null,
      sleep: null,
      strain: null,
      user_first_name: null,
      ...overrides,
    },
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useWhoopDashboard', () => {
  it('skips both secondary fetches while Whoop is disconnected', async () => {
    const fetchMock = mockFetch({
      [DASHBOARD_URL]: ok(dashboardBody({ connected: false })),
    });

    const { result } = renderHook(() => useWhoopDashboard());
    await waitFor(() => expect(result.current.dashboard).not.toBeNull());

    const urls = calledUrls(fetchMock);
    expect(urls.some((u) => u.includes('hrv-trend'))).toBe(false);
    expect(urls.some((u) => u.includes('workouts'))).toBe(false);
  });

  it('skips both secondary fetches while Whoop needs re-authentication', async () => {
    const fetchMock = mockFetch({
      [DASHBOARD_URL]: ok(dashboardBody({ connected: true, needs_reauth: true })),
    });

    const { result } = renderHook(() => useWhoopDashboard());
    await waitFor(() => expect(result.current.dashboard?.needs_reauth).toBe(true));

    const urls = calledUrls(fetchMock);
    expect(urls.some((u) => u.includes('hrv-trend'))).toBe(false);
    expect(urls.some((u) => u.includes('workouts'))).toBe(false);
  });

  it('issues both secondary fetches once Whoop is connected and authorised', async () => {
    const fetchMock = mockFetch({
      [DASHBOARD_URL]: ok(dashboardBody()),
      [HRV_URL]: ok({ data: [{ date: '2024-06-01', hrv_rmssd_milli: 48 }] }),
      [WORKOUTS_URL]: ok({ data: [{ id: 1, sport_name: 'Running' }] }),
    });

    const { result } = renderHook(() => useWhoopDashboard());

    await waitFor(() => {
      const urls = calledUrls(fetchMock);
      expect(urls.some((u) => u.includes('hrv-trend'))).toBe(true);
      expect(urls.some((u) => u.includes('workouts'))).toBe(true);
    });
    await waitFor(() => expect(result.current.hrvPoints).toHaveLength(1));
    expect(result.current.workouts).toHaveLength(1);
  });

  it('reports empty arrays, not null, before the secondary fetches resolve', () => {
    mockFetch({ [DASHBOARD_URL]: ok(dashboardBody({ connected: false })) });

    const { result } = renderHook(() => useWhoopDashboard());

    // Cards map over these directly; null would throw rather than render
    // an empty state.
    expect(result.current.hrvPoints).toEqual([]);
    expect(result.current.workouts).toEqual([]);
  });

  it('reports no secondary error while the secondary fetches are skipped', async () => {
    mockFetch({ [DASHBOARD_URL]: ok(dashboardBody({ connected: false })) });

    const { result } = renderHook(() => useWhoopDashboard());
    await waitFor(() => expect(result.current.dashboard).not.toBeNull());

    // A skipped fetch never attempted anything, so the card must render its
    // empty state rather than a failure that did not happen.
    expect(result.current.hrvError).toBeNull();
    expect(result.current.workoutsError).toBeNull();
  });

  it('surfaces an HRV failure without blanking the page or the workouts card', async () => {
    mockFetch({
      [DASHBOARD_URL]: ok(dashboardBody()),
      [HRV_URL]: { status: 500, body: { error: { code: 'whoop_api_error' } } },
      [WORKOUTS_URL]: ok({ data: [{ id: 1, sport_name: 'Running' }] }),
    });

    const { result } = renderHook(() => useWhoopDashboard());

    await waitFor(() => expect(result.current.hrvError).not.toBeNull());
    // A secondary failure must stay local to its own card.
    expect(result.current.error).toBeNull();
    expect(result.current.dashboard?.connected).toBe(true);
    expect(result.current.workoutsError).toBeNull();
  });

  it('surfaces a workouts failure without blanking the page or the HRV card', async () => {
    mockFetch({
      [DASHBOARD_URL]: ok(dashboardBody()),
      [HRV_URL]: ok({ data: [{ date: '2024-06-01', hrv_rmssd_milli: 48 }] }),
      [WORKOUTS_URL]: { status: 500, body: { error: { code: 'whoop_api_error' } } },
    });

    const { result } = renderHook(() => useWhoopDashboard());

    await waitFor(() => expect(result.current.workoutsError).not.toBeNull());
    expect(result.current.error).toBeNull();
    expect(result.current.dashboard?.connected).toBe(true);
    expect(result.current.hrvError).toBeNull();
  });

  it('surfaces a primary dashboard failure as the page-level error', async () => {
    mockFetch({
      [DASHBOARD_URL]: { status: 500, body: { error: { code: 'whoop_api_error' } } },
    });

    const { result } = renderHook(() => useWhoopDashboard());

    await waitFor(() => expect(result.current.error).not.toBeNull());
    // Secondaries stay skipped: `data` never became connected.
    expect(result.current.hrvError).toBeNull();
    expect(result.current.workoutsError).toBeNull();
  });
});
