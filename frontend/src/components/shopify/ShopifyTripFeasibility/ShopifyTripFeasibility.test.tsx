import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import * as tokenStorage from '../../../auth/tokenStorage';

import type { TripFeasibilityResult } from '../../../types/shopify';
import { ShopifyTripFeasibility } from './ShopifyTripFeasibility';

function result(overrides: Partial<TripFeasibilityResult> = {}): TripFeasibilityResult {
  return {
    verdict: 'go',
    conflicts: [],
    all_day_events: [],
    unavailable_sources: [
      { name: 'booking_com_pricing', reason: 'not_connected' },
      { name: 'render_health', reason: 'not_connected' },
      { name: 'supabase_health', reason: 'not_connected' },
    ],
    shopify_connected: true,
    shopify_needs_reauth: false,
    calendar_connected: true,
    calendar_needs_reauth: false,
    variants_truncated: false,
    orders_truncated: false,
    calendar_truncated: false,
    render_connected: false,
    render_needs_sync: false,
    render_stale: false,
    render_sync_error: false,
    render_truncated: false,
    supabase_connected: false,
    supabase_needs_sync: false,
    supabase_stale: false,
    supabase_sync_error: false,
    calendly_connected: true,
    calendly_needs_reauth: false,
    calendly_truncated: false,
    partial_failures: [],
    ...overrides,
  };
}

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    json: async () => body,
    text: async () => JSON.stringify(body),
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

function submit(start = '2026-06-10', end = '2026-06-14') {
  fireEvent.change(screen.getByLabelText('Start date'), { target: { value: start } });
  fireEvent.change(screen.getByLabelText('End date'), { target: { value: end } });
  fireEvent.click(screen.getByRole('button', { name: 'Check trip' }));
}

afterEach(() => vi.unstubAllGlobals());

describe('ShopifyTripFeasibility', () => {
  it('does not fetch on mount', () => {
    const fn = mockFetch(200, { data: result() });
    render(<ShopifyTripFeasibility />);
    expect(fn).not.toHaveBeenCalled();
  });

  it('prefills the dates from props', () => {
    render(<ShopifyTripFeasibility initialStartDate="2026-06-10" initialEndDate="2026-06-12" />);
    expect(screen.getByLabelText('Start date')).toHaveValue('2026-06-10');
  });

  it.each([
    ['', '2026-06-10', 'Choose both a start and an end date.'],
    ['2026-06-10', '2026-06-09', 'The end date cannot be before the start date.'],
    ['2026-01-01', '2026-12-31', 'The window can be at most 60 days.'],
  ])('blocks submit locally for %s to %s', (start, end, message) => {
    const fn = mockFetch(200, { data: result() });
    render(<ShopifyTripFeasibility />);
    submit(start, end);
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(fn).not.toHaveBeenCalled();
  });

  it('posts the window and renders a clean Go with the unchecked sources line', async () => {
    const fn = mockFetch(200, { data: result() });
    render(<ShopifyTripFeasibility />);
    submit();
    expect(await screen.findByText('Go')).toBeInTheDocument();
    const [url, init] = fn.mock.calls[0];
    expect(url).toBe('/api/v1/trip-feasibility');
    expect(JSON.parse(init.body)).toEqual({ start_date: '2026-06-10', end_date: '2026-06-14' });
    expect(screen.getByText(/booking com pricing \(not connected\)/)).toBeInTheDocument();
    expect(screen.getByText(/render health \(not connected\)/)).toBeInTheDocument();
  });

  it('renders conflicts on a no-go', async () => {
    mockFetch(200, {
      data: result({
        verdict: 'no-go',
        conflicts: [
          {
            type: 'stockout',
            variant_id: 'gid://shopify/ProductVariant/1',
            projected_stockout_date: '2026-06-13',
            event_title: null,
            event_start: null,
            event_end: null,
          },
          {
            type: 'calendar_event',
            variant_id: null,
            projected_stockout_date: null,
            event_title: 'Offsite',
            event_start: '2026-06-11T09:00:00Z',
            event_end: '2026-06-11T10:00:00Z',
          },
        ],
      }),
    });
    render(<ShopifyTripFeasibility />);
    submit();
    expect(await screen.findByText('No-go')).toBeInTheDocument();
    expect(screen.getByText(/Stock runs out on 2026-06-13/)).toBeInTheDocument();
    expect(screen.getByText(/Calendar: Offsite/)).toBeInTheDocument();
  });

  it('lists all-day events as informational', async () => {
    mockFetch(200, {
      data: result({ all_day_events: [{ title: 'Holiday', start_date: '2026-06-12' }] }),
    });
    render(<ShopifyTripFeasibility />);
    submit();
    expect(await screen.findByText('Holiday (2026-06-12)')).toBeInTheDocument();
    expect(screen.getByText('Go')).toBeInTheDocument();
  });

  const degraded: [string, Partial<TripFeasibilityResult>, RegExp][] = [
    ['shopify reauth', { verdict: 'unknown', shopify_needs_reauth: true }, /Reconnect Shopify/],
    ['calendar reauth', { verdict: 'unknown', calendar_needs_reauth: true }, /Reconnect Google Calendar/],
    ['shopify not connected', { verdict: 'unknown', shopify_connected: false }, /Shopify is not connected/],
    ['calendar not connected', { verdict: 'unknown', calendar_connected: false }, /Google Calendar is not connected/],
    ['variants truncated', { verdict: 'unknown', variants_truncated: true }, /product list/],
    ['orders truncated', { verdict: 'unknown', orders_truncated: true }, /sales history/],
    ['calendar truncated', { verdict: 'unknown', calendar_truncated: true }, /more events/],
    ['partial failure', { verdict: 'unknown', partial_failures: ['throttled'] }, /could not be fetched/],
    // A server that wrongly says "go" alongside a failure flag must still not render Go.
    ['go with failure flag', { verdict: 'go', partial_failures: ['orders'] }, /could not be fetched/],
    ['go with truncation', { verdict: 'go', calendar_truncated: true }, /more events/],
  ];

  // The same degradation with a server that wrongly says "go" must also never show Go.
  const wronglyGo = degraded.map(
    ([name, overrides, notice]): [string, Partial<TripFeasibilityResult>, RegExp] => [
      `${name} (server says go)`,
      { ...overrides, verdict: 'go' },
      notice,
    ],
  );

  it.each([...degraded, ...wronglyGo])('never renders Go for %s', async (_name, overrides, notice) => {
    mockFetch(200, { data: result(overrides) });
    render(<ShopifyTripFeasibility />);
    submit();
    expect(await screen.findByText(notice)).toBeInTheDocument();
    expect(screen.getByText('Unknown')).toBeInTheDocument();
    expect(screen.queryByText(/^go$/i)).toBeNull();
  });

  it('never renders Go when the server says go but returns conflicts', async () => {
    mockFetch(200, {
      data: result({
        verdict: 'go',
        conflicts: [
          {
            type: 'stockout',
            variant_id: 'v1',
            projected_stockout_date: '2026-06-11',
            event_title: null,
            event_start: null,
            event_end: null,
          },
        ],
      }),
    });
    render(<ShopifyTripFeasibility />);
    submit();
    expect(await screen.findByText('Unknown')).toBeInTheDocument();
    expect(screen.queryByText(/^go$/i)).toBeNull();
  });

  it.each([
    ['render_stale', 'Render snapshot is more than 24 hours old'],
    ['render_needs_sync', 'Render has never been synced'],
    ['render_sync_error', 'last Render sync failed'],
    ['render_truncated', 'first 10 Render services'],
    ['supabase_stale', 'Supabase snapshot is more than 24 hours old'],
    ['supabase_needs_sync', 'Supabase has never been synced'],
    ['supabase_sync_error', 'last Supabase sync failed'],
  ] as const)('never shows Go when %s, even if the server says go', async (flag, text) => {
    const provider = flag.startsWith('render') ? 'render' : 'supabase';
    mockFetch(200, {
      data: result({ verdict: 'go', [`${provider}_connected`]: true, [flag]: true }),
    });
    render(<ShopifyTripFeasibility />);
    submit();
    expect(await screen.findByText('Unknown')).toBeInTheDocument();
    expect(screen.queryByText(/^go$/i)).toBeNull();
    expect(await screen.findByRole('alert')).toHaveTextContent(text);
  });

  it('shows a connected, fresh infrastructure source as Go', async () => {
    mockFetch(200, { data: result({ render_connected: true, supabase_connected: true }) });
    render(<ShopifyTripFeasibility />);
    submit();
    expect(await screen.findByText('Go')).toBeInTheDocument();
  });

  it('lists an infrastructure conflict with provider, name and state', async () => {
    mockFetch(200, {
      data: result({
        verdict: 'no-go',
        render_connected: true,
        conflicts: [
          {
            type: 'infrastructure',
            provider: 'render',
            infra_name: 'api',
            infra_state: 'build_failed',
            variant_id: null,
            projected_stockout_date: null,
            event_title: null,
            event_start: null,
            event_end: null,
          },
        ],
      }),
    });
    render(<ShopifyTripFeasibility />);
    submit();
    expect(await screen.findByText('Render: api is build_failed')).toBeInTheDocument();
    expect(screen.getByText('No-go')).toBeInTheDocument();
  });

  it('shows reauth prompts as alerts', async () => {
    mockFetch(200, { data: result({ verdict: 'unknown', calendar_needs_reauth: true }) });
    render(<ShopifyTripFeasibility />);
    submit();
    expect(await screen.findByRole('alert')).toHaveTextContent('Reconnect Google Calendar');
  });

  it.each([
    [500, { error: 'boom' }],
    [429, {}],
  ])('shows an error and no verdict for HTTP %s', async (status, body) => {
    mockFetch(status, body);
    render(<ShopifyTripFeasibility />);
    submit();
    expect(await screen.findByText(/Could not run the check/)).toBeInTheDocument();
    expect(screen.queryByText(/^go$/i)).toBeNull();
    expect(screen.queryByText(/Verdict/)).toBeNull();
  });

  it('shows no verdict when the network request fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')));
    render(<ShopifyTripFeasibility />);
    submit();
    expect(await screen.findByText(/network down/)).toBeInTheDocument();
    expect(screen.queryByText(/^go$/i)).toBeNull();
  });

  it('maps a 422 field error onto the date input', async () => {
    mockFetch(422, {
      error: { details: { errors: [{ loc: ['body', 'end_date'], msg: 'bad end' }] } },
    });
    render(<ShopifyTripFeasibility />);
    submit();
    expect(await screen.findByText('bad end')).toBeInTheDocument();
    expect(screen.getByLabelText('End date')).toHaveAttribute('aria-invalid', 'true');
  });

  it('names both providers when both need reauth', async () => {
    mockFetch(200, {
      data: result({ verdict: 'unknown', shopify_needs_reauth: true, calendar_needs_reauth: true }),
    });
    render(<ShopifyTripFeasibility />);
    submit();
    await screen.findAllByRole('alert');
    const text = screen.getAllByRole('alert').map((a) => a.textContent).join(' ');
    expect(text).toMatch(/Reconnect Shopify/);
    expect(text).toMatch(/Reconnect Google Calendar/);
    expect(screen.queryByText(/^go$/i)).toBeNull();
  });

  it.each([
    ['unrecognised verdict', { data: { ...result(), verdict: 'maybe' } }],
    ['missing data envelope', { wrong_key: {} }],
    ['null body', null],
  ])('treats a 200 with %s as an error, never a verdict', async (_n, body) => {
    mockFetch(200, body);
    render(<ShopifyTripFeasibility />);
    submit();
    expect(await screen.findByText(/Could not run the check/)).toBeInTheDocument();
    expect(screen.queryByText(/^go$/i)).toBeNull();
  });

  it('clears the previous Go verdict while a new check is in flight', async () => {
    mockFetch(200, { data: result() });
    render(<ShopifyTripFeasibility />);
    submit();
    expect(await screen.findByText('Go')).toBeInTheDocument();
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
    fireEvent.click(screen.getByRole('button', { name: /check trip|checking/i }));
    await waitFor(() => expect(screen.queryByText('Go')).toBeNull());
  });

  it('a failed re-check does not leave the earlier Go on screen', async () => {
    mockFetch(200, { data: result() });
    render(<ShopifyTripFeasibility />);
    submit();
    expect(await screen.findByText('Go')).toBeInTheDocument();
    mockFetch(500, { error: 'boom' });
    fireEvent.click(screen.getByRole('button', { name: 'Check trip' }));
    expect(await screen.findByText(/Could not run the check/)).toBeInTheDocument();
    expect(screen.queryByText('Go')).toBeNull();
  });

  it('401 clears the session token and shows no verdict', async () => {
    const clear = vi.spyOn(tokenStorage, 'clearToken').mockImplementation(() => {});
    mockFetch(401, {});
    render(<ShopifyTripFeasibility />);
    submit();
    expect(await screen.findByText(/Could not run the check/)).toBeInTheDocument();
    expect(clear).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/^go$/i)).toBeNull();
    clear.mockRestore();
  });

  it('disables the button while a check is in flight', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
    render(<ShopifyTripFeasibility />);
    submit();
    await waitFor(() => expect(screen.getByRole('button')).toBeDisabled());
  });

  it('does not set state after unmount (request aborted)', async () => {
    const abort = vi.spyOn(AbortController.prototype, 'abort');
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
    const { unmount } = render(<ShopifyTripFeasibility />);
    submit();
    unmount();
    expect(abort).toHaveBeenCalled();
    abort.mockRestore();
  });

  it('shows a generic message and never the raw server body on a 5xx', async () => {
    mockFetch(502, '<html>nginx/1.25 internal host 10.0.0.7</html>');
    render(<ShopifyTripFeasibility />);
    submit();
    expect(await screen.findByText(/The check failed \(status 502\)/)).toBeInTheDocument();
    expect(screen.queryByText(/nginx|10\.0\.0\.7/)).not.toBeInTheDocument();
  });
});
