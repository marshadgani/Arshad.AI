import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { DiscountSimulatorResult } from '../../../types/shopify';
import { ShopifyDiscountSimulator } from './ShopifyDiscountSimulator';

function result(overrides: Partial<DiscountSimulatorResult> = {}): DiscountSimulatorResult {
  return {
    connected: true,
    needs_reauth: false,
    valid: true,
    cost_unavailable: false,
    variant_found: true,
    base_price: '50.00',
    discounted_price: '40.00',
    unit_cost: '30.00',
    margin_remaining: '10.00',
    reason: null,
    max_safe_discount_pct: null,
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

function submit(variant: string, percent: string) {
  fireEvent.change(screen.getByLabelText('Variant ID'), { target: { value: variant } });
  fireEvent.change(screen.getByLabelText('Discount %'), { target: { value: percent } });
  fireEvent.click(screen.getByRole('button', { name: 'Check discount' }));
}

afterEach(() => vi.unstubAllGlobals());

describe('ShopifyDiscountSimulator', () => {
  it('does not fetch on mount', () => {
    const fn = mockFetch(200, { data: result() });
    render(<ShopifyDiscountSimulator />);
    expect(fn).not.toHaveBeenCalled();
  });

  it('blocks submit locally for an empty variant and out-of-range percent', () => {
    const fn = mockFetch(200, { data: result() });
    render(<ShopifyDiscountSimulator />);
    submit('', '150');
    expect(screen.getByText('Enter a variant ID.')).toBeInTheDocument();
    expect(screen.getByText('Enter a percentage between 0 and 100.')).toBeInTheDocument();
    expect(fn).not.toHaveBeenCalled();
  });

  it('posts the request and reports a valid margin', async () => {
    const fn = mockFetch(200, { data: result() });
    const onResult = vi.fn();
    render(<ShopifyDiscountSimulator onResult={onResult} />);
    submit(' gid://shopify/ProductVariant/1 ', '20');
    expect(await screen.findByText(/Margin OK/)).toHaveTextContent('10.00');
    const [, init] = fn.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ variant_id: 'gid://shopify/ProductVariant/1', discount_percent: 20 });
    expect(onResult).toHaveBeenCalledWith(expect.objectContaining({ valid: true }));
  });

  it('shows the reason and safe maximum for an invalid code', async () => {
    mockFetch(200, {
      data: result({ valid: false, reason: 'Below cost.', max_safe_discount_pct: '20.00', margin_remaining: '-5.00' }),
    });
    render(<ShopifyDiscountSimulator />);
    submit('v1', '30');
    expect(await screen.findByText(/Below cost\./)).toHaveTextContent('Maximum safe discount: 20.00%');
  });

  it('reports unknown cost as a caveat, not as pass or fail', async () => {
    mockFetch(200, { data: result({ valid: null, cost_unavailable: true }) });
    render(<ShopifyDiscountSimulator />);
    submit('v1', '10');
    expect(await screen.findByText(/Cost unavailable/)).toBeInTheDocument();
    expect(screen.queryByText(/Margin OK/)).not.toBeInTheDocument();
  });

  it('renders server-side 422 messages under the field', async () => {
    mockFetch(422, {
      error: { details: { errors: [{ loc: ['body', 'variant_id'], msg: 'String should match pattern' }] } },
    });
    render(<ShopifyDiscountSimulator />);
    submit('bad id!', '10');
    await waitFor(() => expect(screen.getByText('String should match pattern')).toBeInTheDocument());
  });

  it('disables the button while submitting', async () => {
    let release: (v: unknown) => void = () => {};
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise((r) => { release = r; })));
    render(<ShopifyDiscountSimulator />);
    submit('v1', '10');
    expect(await screen.findByRole('button', { name: 'Checking…' })).toBeDisabled();
    release({ ok: true, status: 200, json: async () => ({ data: result() }) });
    await screen.findByText(/Margin OK/);
  });

  it('shows a server error', async () => {
    mockFetch(500, { error: 'boom' });
    render(<ShopifyDiscountSimulator />);
    submit('v1', '10');
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not run the check');
  });

  // valid stays true in every case: the failure state must win over a stale "valid".
  const failureCases: [string, Partial<DiscountSimulatorResult>, RegExp][] = [
    ['needs reauth', { needs_reauth: true }, /Reconnect Shopify/],
    ['not connected', { connected: false }, /Shopify is not connected/],
    [
      'a failed lookup',
      { partial_failures: ['throttled'] },
      /could not be reached/,
    ],
    [
      'an unknown variant',
      { variant_found: false, reason: 'No variant with that ID exists.' },
      /No variant with that ID exists/,
    ],
  ];
  it.each(failureCases)('never shows "Margin OK" when the result is %s', async (_name, overrides, text) => {
    mockFetch(200, { data: result({ ...overrides, valid: true }) });
    render(<ShopifyDiscountSimulator />);
    submit('gid://shopify/ProductVariant/1', '10');
    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(screen.queryByText(/Margin OK/)).not.toBeInTheDocument();
  });
});
