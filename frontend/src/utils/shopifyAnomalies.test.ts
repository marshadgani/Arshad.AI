import { describe, expect, it } from 'vitest';

import { detectShopifyAnomalies } from './shopifyAnomalies';
import type { ShopifyInsightPoint } from '../types/shopify';

function point(date: string, revenue: number | null, orderCount: number | null = null, partial = false): ShopifyInsightPoint {
  return { date, revenue_amount: revenue == null ? null : revenue.toFixed(2), order_count: orderCount, is_partial_day: partial };
}

describe('detectShopifyAnomalies', () => {
  it('returns insufficient-data when fewer than 5 completed days exist', () => {
    const points = [point('2026-09-10', 100), point('2026-09-11', 110), point('2026-09-12', 90, 4, true)];

    const result = detectShopifyAnomalies(points);

    expect(result.status).toBe('insufficient-data');
    expect(result.anomalies).toEqual([]);
  });

  it('excludes the trailing partial day and truncation gaps from the baseline', () => {
    const points = [
      point('2026-09-08', 100),
      point('2026-09-09', 105),
      point('2026-09-10', 98),
      point('2026-09-11', 102),
      point('2026-09-12', null), // gap
      point('2026-09-13', 30, 1, true), // partial "today"
    ];

    const result = detectShopifyAnomalies(points);

    // Only 4 completed days remain (gap + partial excluded) — still below
    // the 5-day floor, so no anomaly call is made on noisy data.
    expect(result.status).toBe('insufficient-data');
  });

  it('reports no-anomalies for a flat, unremarkable window', () => {
    const points = [
      point('2026-09-08', 100),
      point('2026-09-09', 101),
      point('2026-09-10', 99),
      point('2026-09-11', 100),
      point('2026-09-12', 101),
      point('2026-09-13', 99),
    ];

    const result = detectShopifyAnomalies(points);

    expect(result.status).toBe('no-anomalies');
    expect(result.anomalies).toEqual([]);
  });

  it('flags a day far above the baseline as a spike', () => {
    const points = [
      point('2026-09-08', 100),
      point('2026-09-09', 105),
      point('2026-09-10', 98),
      point('2026-09-11', 102),
      point('2026-09-12', 500),
      point('2026-09-13', 101),
    ];

    const result = detectShopifyAnomalies(points);

    expect(result.status).toBe('anomalies');
    expect(result.anomalies).toHaveLength(1);
    expect(result.anomalies[0]).toMatchObject({ date: '2026-09-12', type: 'spike' });
  });

  it('flags a day far below the baseline as a dip', () => {
    const points = [
      point('2026-09-08', 200),
      point('2026-09-09', 210),
      point('2026-09-10', 195),
      point('2026-09-11', 205),
      point('2026-09-12', 15),
      point('2026-09-13', 198),
    ];

    const result = detectShopifyAnomalies(points);

    expect(result.anomalies.some((a) => a.date === '2026-09-12' && a.type === 'dip')).toBe(true);
  });

  it('flags a zero-revenue day against an active baseline as silent, not a generic dip', () => {
    const points = [
      point('2026-09-08', 200),
      point('2026-09-09', 210),
      point('2026-09-10', 195),
      point('2026-09-11', 205),
      point('2026-09-12', 0),
      point('2026-09-13', 198),
    ];

    const result = detectShopifyAnomalies(points);

    const silentDay = result.anomalies.find((a) => a.date === '2026-09-12');
    expect(silentDay?.type).toBe('silent');
  });

  it('does not treat an all-zero window as anomalous silent days', () => {
    const points = [
      point('2026-09-08', 0),
      point('2026-09-09', 0),
      point('2026-09-10', 0),
      point('2026-09-11', 0),
      point('2026-09-12', 0),
      point('2026-09-13', 0),
    ];

    const result = detectShopifyAnomalies(points);

    expect(result.status).toBe('no-anomalies');
  });

  it('orders anomalies most-recent-first', () => {
    const points = [
      point('2026-09-08', 500),
      point('2026-09-09', 100),
      point('2026-09-10', 98),
      point('2026-09-11', 102),
      point('2026-09-12', 600),
      point('2026-09-13', 101),
    ];

    const result = detectShopifyAnomalies(points);

    const dates = result.anomalies.map((a) => a.date);
    expect(dates).toEqual([...dates].sort().reverse());
  });
});
