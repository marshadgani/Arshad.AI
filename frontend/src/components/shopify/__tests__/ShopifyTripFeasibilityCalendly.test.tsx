import { render, screen } from '@testing-library/react';
import { ShopifyTripFeasibilityOutcome } from '../ShopifyTripFeasibility/ShopifyTripFeasibilityOutcome';
import type { TripFeasibilityResult } from '../../../types/shopify';

const BASE: TripFeasibilityResult = {
  verdict: 'unknown',
  conflicts: [],
  all_day_events: [],
  partial_failures: [],
  unavailable_sources: [],
  shopify_connected: false,
  shopify_needs_reauth: false,
  calendar_connected: false,
  calendar_needs_reauth: false,
  calendar_truncated: false,
  variants_truncated: false,
  orders_truncated: false,
  render_connected: false,
  render_needs_sync: false,
  render_stale: false,
  render_sync_error: false,
  render_truncated: false,
  supabase_connected: false,
  supabase_needs_sync: false,
  supabase_stale: false,
  supabase_sync_error: false,
  calendly_connected: false,
  calendly_needs_reauth: false,
  calendly_truncated: false,
};

describe('ShopifyTripFeasibilityOutcome — Calendly states', () => {
  test('TC-301: not-connected shows CTA text and link to /integrations', () => {
    render(<ShopifyTripFeasibilityOutcome result={BASE} />);
    expect(
      screen.getByText(/Connect Calendly from the Integrations page/i)
    ).toBeInTheDocument();
    const link = screen.queryByRole('link', { name: /integrations/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/integrations');
  });

  test('TC-302: needs-reauth shows reconnect message', () => {
    render(
      <ShopifyTripFeasibilityOutcome
        result={{ ...BASE, calendly_connected: true, calendly_needs_reauth: true }}
      />
    );
    expect(
      screen.getByText(/Calendly token needs to be reconnected/i)
    ).toBeInTheDocument();
  });

  test('TC-303: truncated shows a warning about too many meetings', () => {
    render(
      <ShopifyTripFeasibilityOutcome
        result={{
          ...BASE,
          calendly_connected: true,
          calendly_needs_reauth: false,
          calendly_truncated: true,
        }}
      />
    );
    // The component text is "Too many Calendly meetings to check (truncated); some may have been missed."
    expect(screen.getByText(/too many calendly meetings/i)).toBeInTheDocument();
  });

  test('TC-304: connected with no truncation shows no Calendly degradation', () => {
    render(
      <ShopifyTripFeasibilityOutcome
        result={{
          ...BASE,
          calendly_connected: true,
          calendly_needs_reauth: false,
          calendly_truncated: false,
        }}
      />
    );
    expect(screen.queryByText(/calendly/i)).not.toBeInTheDocument();
  });
});
