/**
 * Tests for BrokerHoldingsCard — the component with the most conditional
 * rendering branches in FEAT-137.
 *
 * Covers every UI state:
 *   connected (normal, truncated, P&L column present/absent)
 *   needs_reauth (Reconnect CTA, no holdings table)
 *   error + stale holdings (last sync failed — showing most recent data)
 *   error + empty holdings (last sync failed — couldn't load)
 *   empty holdings, no error ("No holdings to display")
 *   last_synced_at present and absent
 *
 * Per .claude/rules/frontend.md: queries by role and label only;
 * no snapshot tests; one focused assertion per test.
 */
import { render, screen } from '@testing-library/react';
import { BrokerHoldingsCard } from './BrokerHoldingsCard';
import type { BrokerHoldings } from '../../../types/finance';

function makeBroker(overrides: Partial<BrokerHoldings> = {}): BrokerHoldings {
  return {
    broker: 'upstox',
    display_name: 'Upstox',
    status: 'connected',
    needs_reauth: false,
    currency: 'INR',
    holding_count: 2,
    truncated: false,
    holdings: [
      { symbol: 'TCS', qty: 10, ltp: 3500.5, pnl: 50.0, value: 35005.0 },
      { symbol: 'INFY', qty: 5, ltp: 1500.0, pnl: null, value: 7500.0 },
    ],
    last_synced_at: '2026-09-12T09:30:00+00:00',
    error: null,
    ...overrides,
  };
}

describe('BrokerHoldingsCard — connected state (normal holdings)', () => {
  it('renders a table element when holdings are present', () => {
    render(<BrokerHoldingsCard broker={makeBroker()} />);
    expect(screen.getByRole('table')).toBeInTheDocument();
  });

  it('renders the broker display name as a heading', () => {
    render(<BrokerHoldingsCard broker={makeBroker()} />);
    expect(screen.getByRole('heading', { name: 'Upstox' })).toBeInTheDocument();
  });

  it('renders Symbol column header', () => {
    render(<BrokerHoldingsCard broker={makeBroker()} />);
    expect(screen.getByRole('columnheader', { name: 'Symbol' })).toBeInTheDocument();
  });

  it('renders Qty column header', () => {
    render(<BrokerHoldingsCard broker={makeBroker()} />);
    expect(screen.getByRole('columnheader', { name: 'Qty' })).toBeInTheDocument();
  });

  it('renders LTP column header', () => {
    render(<BrokerHoldingsCard broker={makeBroker()} />);
    expect(screen.getByRole('columnheader', { name: 'LTP' })).toBeInTheDocument();
  });

  it('renders Value column header', () => {
    render(<BrokerHoldingsCard broker={makeBroker()} />);
    expect(screen.getByRole('columnheader', { name: 'Value' })).toBeInTheDocument();
  });

  it('renders P&L column when at least one holding has a non-null pnl', () => {
    // makeBroker default: TCS has pnl=50.0
    render(<BrokerHoldingsCard broker={makeBroker()} />);
    expect(screen.getByRole('columnheader', { name: /P&L/i })).toBeInTheDocument();
  });

  it('omits P&L column when all holdings have null pnl', () => {
    const broker = makeBroker({
      holdings: [
        { symbol: 'TCS', qty: 10, ltp: 3500.5, pnl: null, value: 35005.0 },
        { symbol: 'INFY', qty: 5, ltp: 1500.0, pnl: null, value: 7500.0 },
      ],
    });
    render(<BrokerHoldingsCard broker={broker} />);
    expect(screen.queryByRole('columnheader', { name: /P&L/i })).not.toBeInTheDocument();
  });

  it('renders each holding symbol as a table cell', () => {
    render(<BrokerHoldingsCard broker={makeBroker()} />);
    expect(screen.getByText('TCS')).toBeInTheDocument();
    expect(screen.getByText('INFY')).toBeInTheDocument();
  });

  it('renders "as of" label when last_synced_at is provided', () => {
    render(<BrokerHoldingsCard broker={makeBroker()} />);
    expect(screen.getByText(/as of/i)).toBeInTheDocument();
  });

  it('does NOT render an "as of" label when last_synced_at is null', () => {
    render(<BrokerHoldingsCard broker={makeBroker({ last_synced_at: null })} />);
    expect(screen.queryByText(/as of/i)).not.toBeInTheDocument();
  });

  it('does not render a status error message when connected and no error', () => {
    render(<BrokerHoldingsCard broker={makeBroker()} />);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('renders the Upstox sub-label for long-term holdings', () => {
    render(<BrokerHoldingsCard broker={makeBroker({ broker: 'upstox' })} />);
    expect(screen.getByText(/long-term holdings/i)).toBeInTheDocument();
  });

  it('does NOT render the Upstox sub-label for Zerodha', () => {
    render(
      <BrokerHoldingsCard
        broker={makeBroker({ broker: 'zerodha_kite', display_name: 'Zerodha Kite' })}
      />,
    );
    expect(screen.queryByText(/long-term holdings/i)).not.toBeInTheDocument();
  });
});

describe('BrokerHoldingsCard — needs_reauth / expired state', () => {
  it('renders a "Reconnect" link pointing to /integrations', () => {
    render(
      <BrokerHoldingsCard broker={makeBroker({ needs_reauth: true, status: 'expired' })} />,
    );
    const link = screen.getByRole('link', { name: 'Reconnect' });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/integrations');
  });

  it('does NOT render a holdings table when needs_reauth is true', () => {
    render(
      <BrokerHoldingsCard broker={makeBroker({ needs_reauth: true, status: 'expired' })} />,
    );
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('includes the broker display name in the reconnect title', () => {
    render(
      <BrokerHoldingsCard
        broker={makeBroker({
          needs_reauth: true,
          status: 'expired',
          display_name: 'Zerodha Kite',
        })}
      />,
    );
    expect(
      screen.getByRole('heading', { name: /Reconnect Zerodha Kite/i }),
    ).toBeInTheDocument();
  });

  it('does not render an error status message when needs_reauth (dedicated flow owns messaging)', () => {
    render(
      <BrokerHoldingsCard broker={makeBroker({ needs_reauth: true, status: 'expired' })} />,
    );
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});

describe('BrokerHoldingsCard — error state', () => {
  it('renders status message about stale data when error is set and holdings are present', () => {
    const broker = makeBroker({ status: 'error', error: 'sync failed — sanitized on wire' });
    render(<BrokerHoldingsCard broker={broker} />);
    const msg = screen.getByRole('status');
    expect(msg).toHaveTextContent(/last sync failed.*most recent data/i);
  });

  it('still renders the holdings table underneath the error when holdings are present', () => {
    const broker = makeBroker({ status: 'error', error: 'sync failed' });
    render(<BrokerHoldingsCard broker={broker} />);
    expect(screen.getByRole('table')).toBeInTheDocument();
  });

  it('renders status message about unavailable data when error set and holdings are empty', () => {
    const broker = makeBroker({
      status: 'error',
      error: 'sync failed',
      holdings: [],
      holding_count: 0,
    });
    render(<BrokerHoldingsCard broker={broker} />);
    const msg = screen.getByRole('status');
    expect(msg).toHaveTextContent(/last sync failed.*couldn.*t load/i);
  });

  it('does not render a table when error is set and holdings are empty', () => {
    const broker = makeBroker({
      status: 'error',
      error: 'sync failed',
      holdings: [],
      holding_count: 0,
    });
    render(<BrokerHoldingsCard broker={broker} />);
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('does NOT render the raw error string from the server (component owns the copy)', () => {
    // The component uses its own hard-coded copy; it must not echo the wire value.
    const broker = makeBroker({
      status: 'error',
      error: 'HTTPStatusError: 401 https://api.upstox.com',
      holdings: [],
      holding_count: 0,
    });
    render(<BrokerHoldingsCard broker={broker} />);
    expect(screen.queryByText(/httpstatuserror/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/upstox.com/i)).not.toBeInTheDocument();
  });
});

describe('BrokerHoldingsCard — empty holdings state (no error)', () => {
  it('renders "No holdings to display" when holdings=[] and no error', () => {
    const broker = makeBroker({ holdings: [], holding_count: 0, error: null });
    render(<BrokerHoldingsCard broker={broker} />);
    expect(screen.getByText(/no holdings to display/i)).toBeInTheDocument();
  });

  it('does not render a table when holdings are empty', () => {
    const broker = makeBroker({ holdings: [], holding_count: 0, error: null });
    render(<BrokerHoldingsCard broker={broker} />);
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('does not render a "Reconnect" link when needs_reauth is false and holdings are empty', () => {
    const broker = makeBroker({ holdings: [], holding_count: 0, error: null });
    render(<BrokerHoldingsCard broker={broker} />);
    expect(screen.queryByRole('link', { name: /reconnect/i })).not.toBeInTheDocument();
  });
});

describe('BrokerHoldingsCard — truncated state', () => {
  function truncatedBroker() {
    return makeBroker({
      holdings: Array.from({ length: 10 }, (_, i) => ({
        symbol: `SYM${i}`,
        qty: 1,
        ltp: 100.0,
        pnl: null,
        value: 100.0,
      })),
      holding_count: 42,
      truncated: true,
    });
  }

  it('renders a truncation notice when truncated=true', () => {
    render(<BrokerHoldingsCard broker={truncatedBroker()} />);
    expect(screen.getByText(/showing top 10 of 42 holdings/i)).toBeInTheDocument();
  });

  it('does NOT render a truncation notice when truncated=false', () => {
    render(<BrokerHoldingsCard broker={makeBroker({ truncated: false, holding_count: 2 })} />);
    expect(screen.queryByText(/showing top/i)).not.toBeInTheDocument();
  });

  it('still renders the holdings table when truncated', () => {
    render(<BrokerHoldingsCard broker={truncatedBroker()} />);
    expect(screen.getByRole('table')).toBeInTheDocument();
  });
});
