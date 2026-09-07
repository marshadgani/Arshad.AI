/**
 * Characterisation tests for the health formatters.
 *
 * These functions were extracted verbatim out of HealthFitness.tsx and
 * AppleHealthCard.tsx during the FEAT-120 restructure. The tests pin the
 * behaviour that move had to preserve — in particular that a null metric
 * renders as an em dash and never as "0", which on a health dashboard is
 * the difference between "no reading" and a real reading of zero.
 */

import { describe, expect, it, vi } from 'vitest';

import {
  EM_DASH,
  fmt1,
  fmtDate,
  formatCount,
  formatMetric,
  kilojoulesToKcal,
  millisToHM,
  pct,
  recoveryBand,
  recoveryColor,
  recoveryLabel,
  timeAgo,
} from './healthFormat';

describe('null handling', () => {
  it.each([
    ['millisToHM', millisToHM],
    ['pct', pct],
    ['fmt1', fmt1],
    ['fmtDate', fmtDate],
    ['formatCount', formatCount],
    ['kilojoulesToKcal', kilojoulesToKcal],
  ])('%s renders null as an em dash', (_name, fn) => {
    expect(fn(null as never)).toBe(EM_DASH);
  });

  it('formatMetric renders null as an em dash without the unit', () => {
    expect(formatMetric(null, ' bpm')).toBe(EM_DASH);
  });

  it('distinguishes a real zero reading from missing data', () => {
    expect(pct(0)).toBe('0%');
    expect(fmt1(0)).toBe('0.0');
    expect(formatCount(0)).toBe('0');
    expect(pct(null)).toBe(EM_DASH);
  });
});

describe('millisToHM', () => {
  it('splits milliseconds into whole hours and minutes', () => {
    expect(millisToHM(5_400_000)).toBe('1h 30m');
  });

  it('reports sub-hour durations as 0h', () => {
    expect(millisToHM(60_000)).toBe('0h 1m');
  });
});

describe('pct', () => {
  it('rounds to the nearest whole percent', () => {
    expect(pct(94.6)).toBe('95%');
  });
});

describe('formatMetric', () => {
  it('appends the unit at the requested precision', () => {
    expect(formatMetric(55, ' bpm')).toBe('55 bpm');
    expect(formatMetric(7.46, 'h', 1)).toBe('7.5h');
  });
});

describe('kilojoulesToKcal', () => {
  it('converts kilojoules to rounded kilocalories', () => {
    expect(kilojoulesToKcal(4184)).toBe('1000 kcal');
  });
});

describe('formatCount', () => {
  it('groups thousands', () => {
    expect(formatCount(12431)).toBe((12431).toLocaleString());
  });
});

describe('timeAgo', () => {
  it('returns null when there is no timestamp, so the caller can omit the line', () => {
    expect(timeAgo(null)).toBeNull();
  });

  it.each([
    [30_000, 'just now'],
    [5 * 60_000, '5m ago'],
    [3 * 3_600_000, '3h ago'],
    [2 * 86_400_000, '2d ago'],
  ])('describes an age of %ims', (ageMs, expected) => {
    const now = new Date('2026-09-07T12:00:00.000Z').getTime();
    vi.spyOn(Date, 'now').mockReturnValue(now);
    expect(timeAgo(new Date(now - ageMs).toISOString())).toBe(expected);
    vi.restoreAllMocks();
  });

  it('reports a future timestamp as "just now" rather than a negative age', () => {
    const now = new Date('2026-09-07T12:00:00.000Z').getTime();
    vi.spyOn(Date, 'now').mockReturnValue(now);
    expect(timeAgo(new Date(now + 30_000).toISOString())).toBe('just now');
    vi.restoreAllMocks();
  });
});

describe('recovery scale', () => {
  it.each([
    [null, 'none', 'No data'],
    [10, 'low', 'Low'],
    [33, 'low', 'Low'],
    [34, 'moderate', 'Moderate'],
    [66, 'moderate', 'Moderate'],
    [67, 'optimal', 'Optimal'],
    [100, 'optimal', 'Optimal'],
  ])('bands a score of %s', (score, band, label) => {
    expect(recoveryBand(score as number | null)).toBe(band);
    expect(recoveryLabel(score as number | null)).toBe(label);
  });

  it('keeps colour and label in agreement across the bands', () => {
    expect(recoveryColor(80)).toBe('var(--status-ok)');
    expect(recoveryColor(50)).toBe('var(--status-warn)');
    expect(recoveryColor(10)).toBe('var(--status-danger)');
    expect(recoveryColor(null)).toBe('var(--text-muted)');
  });
});
