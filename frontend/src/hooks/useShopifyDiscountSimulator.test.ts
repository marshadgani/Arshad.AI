/**
 * useShopifyDiscountSimulator — mutation hook contract.
 *
 * Unlike the other Shopify hooks, this one is NOT a useFetch wrapper:
 * it fires a POST only on user action (checkDiscount), never on mount.
 * Tests stub global `fetch` directly.
 */

import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useShopifyDiscountSimulator } from './useShopifyDiscountSimulator';

const VALID_VARIANT = 'gid://shopify/ProductVariant/123';
const TOKEN_KEY = 'arshad.ai:jwt';

function mockFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : String(status),
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  });
}

beforeEach(() => {
  // Ensure a token is present so Authorization header tests are deterministic.
  window.localStorage.setItem(TOKEN_KEY, 'test-token');
});

afterEach(() => {
  window.localStorage.removeItem(TOKEN_KEY);
  vi.restoreAllMocks();
});

describe('useShopifyDiscountSimulator', () => {
  it('starts with no result, no loading, no errors', () => {
    const { result } = renderHook(() => useShopifyDiscountSimulator());

    expect(result.current.result).toBeNull();
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.fieldErrors).toEqual({});
  });

  it('does not fire a request on mount', () => {
    const spy = vi.spyOn(global, 'fetch');
    renderHook(() => useShopifyDiscountSimulator());
    expect(spy).not.toHaveBeenCalled();
  });

  it('POSTs to the discount-simulator endpoint', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve({ data: { connected: true, valid: true } }),
      text: () => Promise.resolve(''),
    } as Response);

    const { result } = renderHook(() => useShopifyDiscountSimulator());

    await act(async () => {
      await result.current.checkDiscount(VALID_VARIANT, 10);
    });

    expect(spy).toHaveBeenCalledWith(
      '/api/v1/shopify/discount-simulator',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('sends the Authorization header when a token is present', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve({ data: { connected: true, valid: true } }),
      text: () => Promise.resolve(''),
    } as Response);

    const { result } = renderHook(() => useShopifyDiscountSimulator());

    await act(async () => {
      await result.current.checkDiscount(VALID_VARIANT, 10);
    });

    const [, init] = spy.mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer test-token');
  });

  it('does NOT send Authorization header when no token is stored', async () => {
    window.localStorage.removeItem(TOKEN_KEY);
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve({ data: { connected: true, valid: true } }),
      text: () => Promise.resolve(''),
    } as Response);

    const { result } = renderHook(() => useShopifyDiscountSimulator());

    await act(async () => {
      await result.current.checkDiscount(VALID_VARIANT, 10);
    });

    const [, init] = spy.mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers['Authorization']).toBeUndefined();
  });

  it('sets result on a successful 200 response', async () => {
    const fakeResult = { connected: true, valid: true, discounted_price: '45.00' };
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve({ data: fakeResult }),
      text: () => Promise.resolve(''),
    } as Response);

    const { result } = renderHook(() => useShopifyDiscountSimulator());

    await act(async () => {
      await result.current.checkDiscount(VALID_VARIANT, 10);
    });

    expect(result.current.result).toEqual(fakeResult);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it('sets fieldErrors on a 422 response with per-field detail', async () => {
    const body422 = {
      error: {
        details: {
          errors: [
            { loc: ['body', 'variant_id'], msg: 'Invalid characters in variant ID.' },
          ],
        },
      },
    };
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 422,
      statusText: 'Unprocessable Entity',
      json: () => Promise.resolve(body422),
      text: () => Promise.resolve(JSON.stringify(body422)),
    } as Response);

    const { result } = renderHook(() => useShopifyDiscountSimulator());

    await act(async () => {
      await result.current.checkDiscount('invalid\x00id', 10);
    });

    expect(result.current.fieldErrors.variant_id).toBeTruthy();
    expect(result.current.result).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('sets error on a non-200, non-422 response', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: () => Promise.resolve({}),
      text: () => Promise.resolve('Internal Server Error'),
    } as Response);

    const { result } = renderHook(() => useShopifyDiscountSimulator());

    await act(async () => {
      await result.current.checkDiscount(VALID_VARIANT, 10);
    });

    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.result).toBeNull();
  });

  it('clears token and sets error on a 401 response', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 401,
      statusText: 'Unauthorized',
      json: () => Promise.resolve({}),
      text: () => Promise.resolve(''),
    } as Response);

    const { result } = renderHook(() => useShopifyDiscountSimulator());

    await act(async () => {
      await result.current.checkDiscount(VALID_VARIANT, 10);
    });

    expect(window.localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(result.current.error?.message).toMatch(/401/);
  });

  it('sends the request body as JSON with variant_id and discount_percent', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve({ data: { connected: true } }),
      text: () => Promise.resolve(''),
    } as Response);

    const { result } = renderHook(() => useShopifyDiscountSimulator());

    await act(async () => {
      await result.current.checkDiscount(VALID_VARIANT, 15.5);
    });

    const [, init] = spy.mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({ variant_id: VALID_VARIANT, discount_percent: 15.5 });
  });

  it('resets result and errors before each new request', async () => {
    // First call succeeds.
    vi.spyOn(global, 'fetch')
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: () => Promise.resolve({ data: { connected: true, valid: true } }),
        text: () => Promise.resolve(''),
      } as Response)
      // Second call errors.
      .mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        json: () => Promise.resolve({}),
        text: () => Promise.resolve('boom'),
      } as Response);

    const { result } = renderHook(() => useShopifyDiscountSimulator());

    await act(async () => {
      await result.current.checkDiscount(VALID_VARIANT, 10);
    });
    expect(result.current.result).not.toBeNull();

    await act(async () => {
      await result.current.checkDiscount(VALID_VARIANT, 20);
    });
    // Prior result must be cleared even though this call failed.
    expect(result.current.result).toBeNull();
    expect(result.current.error).not.toBeNull();
  });
});
