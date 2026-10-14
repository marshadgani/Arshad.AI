import { render, screen } from '@testing-library/react';
import { ShopifyTripFeasibilityOutcome } from './ShopifyTripFeasibilityOutcome';
import type { TripFeasibilityResult } from '../../../types/shopify';

const BASE: TripFeasibilityResult = {
  verdict: 'go',
  conflicts: [],
  all_day_events: [],
  unavailable_sources: [],
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
};

const result = (o: Partial<TripFeasibilityResult> = {}): TripFeasibilityResult => ({ ...BASE, ...o });

describe('ShopifyTripFeasibilityOutcome — Calendly', () => {
  it('shows no Calendly message when connected and clean', () => {
    render(<ShopifyTripFeasibilityOutcome result={result()} />);
    expect(screen.queryByText(/Calendly/)).toBeNull();
    expect(screen.getByText('Go')).toBeInTheDocument();
  });

  it('asks to connect Calendly and never shows Go when not connected', () => {
    render(
      <ShopifyTripFeasibilityOutcome
        result={result({ calendly_connected: false })}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Connect Calendly from the Integrations page');
    expect(screen.getByText('Unknown')).toBeInTheDocument();
    expect(screen.queryByText(/Not checked/)).toBeNull();
  });

  it('does not report truncation while reauth is pending', () => {
    render(
      <ShopifyTripFeasibilityOutcome
        result={result({ calendly_needs_reauth: true, calendly_truncated: true })}
      />,
    );
    expect(screen.getAllByRole('alert')).toHaveLength(1);
  });

  it('reports a failed Calendly read and never shows Go', () => {
    render(
      <ShopifyTripFeasibilityOutcome
        result={result({ verdict: 'unknown', partial_failures: ['calendly'] })}
      />,
    );
    expect(screen.getByRole('status')).toHaveTextContent('Some data could not be fetched (calendly)');
    expect(screen.getByText('Unknown')).toBeInTheDocument();
  });

  it('downgrades a Go to Unknown when Calendly is not connected', () => {
    render(<ShopifyTripFeasibilityOutcome result={result({ calendly_connected: false })} />);
    expect(screen.queryByText('Go')).toBeNull();
    expect(screen.getByText('Unknown')).toBeInTheDocument();
  });

  it('asks to reconnect when the token needs reauth', () => {
    render(<ShopifyTripFeasibilityOutcome result={result({ calendly_needs_reauth: true })} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Calendly token needs to be reconnected');
  });

  it('warns when too many meetings were returned', () => {
    render(<ShopifyTripFeasibilityOutcome result={result({ calendly_truncated: true })} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Too many Calendly meetings');
  });

  it('lists a Calendly meeting conflict', () => {
    render(
      <ShopifyTripFeasibilityOutcome
        result={result({
          verdict: 'no-go',
          conflicts: [
            {
              type: 'calendly_event',
              calendly_event_title: 'Board sync',
              calendly_event_start: '2026-06-12T09:00:00Z',
              calendly_event_end: '2026-06-12T09:30:00Z',
              variant_id: null,
              projected_stockout_date: null,
              event_title: null,
              event_start: null,
              event_end: null,
            },
          ],
        })}
      />,
    );
    expect(screen.getByRole('list', { name: 'Conflicts' })).toHaveTextContent('Calendly: Board sync');
  });
});
