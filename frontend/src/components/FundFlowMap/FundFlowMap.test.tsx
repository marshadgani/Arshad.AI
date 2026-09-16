import { render, screen } from '@testing-library/react';
import { vi } from 'vitest';

import FundFlowMap from './FundFlowMap';

const LEGEND_LABELS = [
  'Income Source',
  'Vendor',
  'Saudi Bank',
  'Exchange',
  'NRE Account',
  'NRO Account',
  'Savings Account',
  'Family',
  'Credit Card',
  'Investment',
  'Subscription',
  'Expense',
];

describe('FundFlowMap', () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchSpy = vi.spyOn(globalThis, 'fetch') as unknown as ReturnType<typeof vi.fn>;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the honest "Static map · not live data" badge', () => {
    render(<FundFlowMap />);
    expect(screen.getByText('Static map · not live data')).toBeInTheDocument();
  });

  it('renders the honest sub-text explaining balances/transfers are not connected', () => {
    render(<FundFlowMap />);
    expect(
      screen.getByText(/Hand-drawn from your real accounts · balances and transfers are not connected · v13/)
    ).toBeInTheDocument();
  });

  it('does not render the old misleading "Full money map" label', () => {
    render(<FundFlowMap />);
    expect(screen.queryByText(/Full money map/)).toBeNull();
  });

  it('renders all 12 legend entries', () => {
    render(<FundFlowMap />);
    for (const label of LEGEND_LABELS) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it('exposes the diagram as a named, keyboard-focusable group', () => {
    render(<FundFlowMap />);
    const group = screen.getByRole('group', { name: /fund flow diagram/i });
    expect(group).toBeInTheDocument();
    expect(group).toHaveAttribute('tabindex', '0');
  });

  it('mounts the static SVG inside the diagram region', () => {
    render(<FundFlowMap />);
    const group = screen.getByRole('group', { name: /fund flow diagram/i });
    expect(group.querySelector('svg')).not.toBeNull();
  });

  it('issues zero fetch calls', () => {
    render(<FundFlowMap />);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
