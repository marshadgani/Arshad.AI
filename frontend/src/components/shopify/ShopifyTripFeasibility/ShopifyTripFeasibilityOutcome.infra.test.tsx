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
  partial_failures: [],
};

function result(overrides: Partial<TripFeasibilityResult> = {}): TripFeasibilityResult {
  return { ...BASE, ...overrides };
}

function infra_conflict(
  provider: 'render' | 'supabase',
  name: string,
  state: string,
): TripFeasibilityResult['conflicts'][number] {
  return {
    type: 'infrastructure',
    provider,
    infra_name: name,
    infra_state: state,
    variant_id: null,
    projected_stockout_date: null,
    event_title: null,
    event_start: null,
    event_end: null,
  };
}

describe('ShopifyTripFeasibilityOutcome — infra conflicts', () => {
  it('renders a Render suspended conflict', () => {
    const r = result({
      verdict: 'no-go',
      render_connected: true,
      conflicts: [infra_conflict('render', 'my-api', 'suspended')],
    });
    render(<ShopifyTripFeasibilityOutcome result={r} />);
    expect(screen.getByText(/Render: my-api is suspended/i)).toBeInTheDocument();
    expect(screen.getByText(/No-go/i)).toBeInTheDocument();
  });

  it('renders a Supabase inactive conflict', () => {
    const r = result({
      verdict: 'no-go',
      supabase_connected: true,
      conflicts: [infra_conflict('supabase', 'my-db', 'INACTIVE')],
    });
    render(<ShopifyTripFeasibilityOutcome result={r} />);
    expect(screen.getByText(/Supabase: my-db is INACTIVE/i)).toBeInTheDocument();
  });

  it('shows render_stale warning when render is connected and stale', () => {
    const r = result({
      verdict: 'unknown',
      render_connected: true,
      render_stale: true,
    });
    render(<ShopifyTripFeasibilityOutcome result={r} />);
    expect(
      screen.getByText(/Render snapshot is more than 24 hours old/i),
    ).toBeInTheDocument();
  });

  it('shows render_needs_sync warning when render never synced', () => {
    const r = result({
      verdict: 'unknown',
      render_connected: true,
      render_needs_sync: true,
    });
    render(<ShopifyTripFeasibilityOutcome result={r} />);
    expect(screen.getByText(/Render has never been synced/i)).toBeInTheDocument();
  });

  it('shows render_sync_error warning', () => {
    const r = result({
      verdict: 'unknown',
      render_connected: true,
      render_sync_error: true,
    });
    render(<ShopifyTripFeasibilityOutcome result={r} />);
    expect(screen.getByText(/last Render sync failed/i)).toBeInTheDocument();
  });

  it('shows render_truncated warning', () => {
    const r = result({
      verdict: 'unknown',
      render_connected: true,
      render_truncated: true,
    });
    render(<ShopifyTripFeasibilityOutcome result={r} />);
    expect(screen.getByText(/first 10 Render services/i)).toBeInTheDocument();
  });

  it('shows supabase_stale warning', () => {
    const r = result({
      verdict: 'unknown',
      supabase_connected: true,
      supabase_stale: true,
    });
    render(<ShopifyTripFeasibilityOutcome result={r} />);
    expect(
      screen.getByText(/Supabase snapshot is more than 24 hours old/i),
    ).toBeInTheDocument();
  });

  it('renders go verdict when no conflicts and no degradations', () => {
    render(<ShopifyTripFeasibilityOutcome result={BASE} />);
    expect(screen.getByText(/Go/)).toBeInTheDocument();
  });
});
