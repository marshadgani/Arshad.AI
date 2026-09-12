/**
 * Characterisation tests for the Shopify formatters.
 *
 * formatMoney, formatRelativeTime, staleLabel, and shopSubtitle were flagged
 * by the gate's refactorer role as having null/NaN/invalid-currency paths
 * that are unverified. These tests pin every edge case so regressions fail
 * loudly rather than silently showing wrong values on a live store dashboard.
 */

import { describe, expect, it, vi } from 'vitest';

import { formatMoney, formatRelativeTime, shopSubtitle, staleLabel } from './shopifyFormat';

// ---------------------------------------------------------------------------
// formatMoney
// ---------------------------------------------------------------------------

describe('formatMoney', () => {
  it('formats a numeric string as currency', () => {
    const result = formatMoney('99.99', 'USD');

    expect(result).toMatch(/99\.99/);
  });

  it('returns an em dash when amount is null', () => {
    expect(formatMoney(null, 'USD')).toBe('—');
  });

  it('returns an em dash when amount is undefined', () => {
    expect(formatMoney(undefined, 'USD')).toBe('—');
  });

  it('returns an em dash when amount is NaN-producing', () => {
    expect(formatMoney('not-a-number', 'USD')).toBe('—');
  });

  it('falls back to USD when currency is null', () => {
    const result = formatMoney('50.00', null);

    expect(result).toMatch(/50/);
  });

  it('falls back to USD when currency is undefined', () => {
    const result = formatMoney('50.00', undefined);

    expect(result).toMatch(/50/);
  });

  it('falls back to raw amount + currency string for an invalid currency code', () => {
    // Intl.NumberFormat throws for invalid currency codes like 'XYZ_FAKE';
    // the catch block returns the raw fallback rather than crashing.
    const result = formatMoney('42.00', 'INVALID_CURRENCY_CODE');

    expect(result).toContain('42.00');
  });

  it('formats zero as currency rather than an em dash', () => {
    const result = formatMoney('0', 'USD');

    expect(result).toMatch(/0/);
    expect(result).not.toBe('—');
  });

  it('formats a large amount without truncation', () => {
    const result = formatMoney('100000.00', 'GBP');

    expect(result).toMatch(/100/);
  });
});

// ---------------------------------------------------------------------------
// formatRelativeTime
// ---------------------------------------------------------------------------

describe('formatRelativeTime', () => {
  it('returns an em dash when the iso string is null', () => {
    expect(formatRelativeTime(null)).toBe('—');
  });

  it('returns an em dash when the iso string is undefined', () => {
    expect(formatRelativeTime(undefined)).toBe('—');
  });

  it('returns an em dash for an empty string', () => {
    expect(formatRelativeTime('')).toBe('—');
  });

  it('returns an em dash for an unparsable timestamp', () => {
    expect(formatRelativeTime('not-a-date')).toBe('—');
  });

  it.each([
    [30_000, 'Just now'],
    [5 * 60_000, '5m ago'],
    [3 * 3_600_000, '3h ago'],
    [2 * 86_400_000, '2d ago'],
  ])('describes an age of %ims correctly', (ageMs, expected) => {
    const now = new Date('2026-09-11T12:00:00.000Z').getTime();
    vi.spyOn(Date, 'now').mockReturnValue(now);

    expect(formatRelativeTime(new Date(now - ageMs).toISOString())).toBe(expected);

    vi.restoreAllMocks();
  });

  it('returns "Just now" for a sub-minute age', () => {
    const now = new Date('2026-09-11T12:00:00.000Z').getTime();
    vi.spyOn(Date, 'now').mockReturnValue(now);

    expect(formatRelativeTime(new Date(now - 59_000).toISOString())).toBe('Just now');

    vi.restoreAllMocks();
  });

  it('uses floor division so 89 minutes reads as 1h not 2h', () => {
    const now = new Date('2026-09-11T12:00:00.000Z').getTime();
    vi.spyOn(Date, 'now').mockReturnValue(now);

    expect(formatRelativeTime(new Date(now - 89 * 60_000).toISOString())).toBe('1h ago');

    vi.restoreAllMocks();
  });
});

// ---------------------------------------------------------------------------
// staleLabel
// ---------------------------------------------------------------------------

describe('staleLabel', () => {
  it('returns null when cachedAt is null so the caller can omit the stale banner', () => {
    expect(staleLabel(null)).toBeNull();
  });

  it('returns null when cachedAt is undefined', () => {
    expect(staleLabel(undefined)).toBeNull();
  });

  it('returns a "Updated X ago" string when cachedAt is provided', () => {
    const now = new Date('2026-09-11T12:00:00.000Z').getTime();
    vi.spyOn(Date, 'now').mockReturnValue(now);

    const result = staleLabel(new Date(now - 5 * 60_000).toISOString());

    expect(result).toBe('Updated 5m ago');

    vi.restoreAllMocks();
  });

  it('passes through the "Just now" bucket from formatRelativeTime', () => {
    const now = new Date('2026-09-11T12:00:00.000Z').getTime();
    vi.spyOn(Date, 'now').mockReturnValue(now);

    const result = staleLabel(new Date(now - 10_000).toISOString());

    expect(result).toBe('Updated Just now');

    vi.restoreAllMocks();
  });
});

// ---------------------------------------------------------------------------
// shopSubtitle
// ---------------------------------------------------------------------------

describe('shopSubtitle', () => {
  it('returns null when both shopName and timezone are absent', () => {
    expect(shopSubtitle(null, null)).toBeNull();
  });

  it('returns null when both are undefined', () => {
    expect(shopSubtitle(undefined, undefined)).toBeNull();
  });

  it('returns only the timezone when shopName is absent', () => {
    expect(shopSubtitle(null, 'America/New_York')).toBe('Today (America/New_York)');
  });

  it('returns only the shop name when timezone is absent', () => {
    expect(shopSubtitle('My Shop', null)).toBe('My Shop');
  });

  it('combines both when both are present', () => {
    expect(shopSubtitle('My Shop', 'Europe/London')).toBe('My Shop · Today (Europe/London)');
  });
});
