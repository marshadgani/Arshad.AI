/**
 * Characterisation tests for formatRelativeTime. Moved verbatim from
 * shopifyFormat.test.ts when the function relocated to utils/time.ts.
 */

import { describe, expect, it, vi } from 'vitest';

import { formatRelativeTime } from './time';

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
