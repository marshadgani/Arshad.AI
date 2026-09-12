/**
 * Display formatting for health metrics.
 *
 * Pulled out of the page and card components because every one of these is
 * a pure value->string function with no React in it: they are the part of
 * the Health dashboard most worth unit-testing, and they were previously
 * duplicated between HealthFitness.tsx and AppleHealthCard.tsx.
 *
 * One shared rule: a null metric renders as EM_DASH, never as "0" or "".
 * Zero is a real reading; missing data is not, and the two must not look
 * the same on a health dashboard.
 */

export const EM_DASH = '—';

/** Milliseconds as "7h 32m" — used for sleep stage durations. */
export function millisToHM(ms: number | null): string {
  if (ms == null) return EM_DASH;
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  return `${h}h ${m}m`;
}

/** Rounded percentage, e.g. "94%". */
export function pct(v: number | null): string {
  return v != null ? `${Math.round(v)}%` : EM_DASH;
}

/** One decimal place, e.g. "12.4" — strain and respiratory rate. */
export function fmt1(v: number | null): string {
  return v != null ? v.toFixed(1) : EM_DASH;
}

/** Short day label, e.g. "4 Sep". */
export function fmtDate(iso: string | null): string {
  if (!iso) return EM_DASH;
  return new Date(iso).toLocaleDateString('en-GB', { month: 'short', day: 'numeric' });
}

/** Value with a unit suffix, e.g. formatMetric(55, ' bpm') -> "55 bpm". */
export function formatMetric(value: number | null, unit: string, digits = 0): string {
  return value != null ? `${value.toFixed(digits)}${unit}` : EM_DASH;
}

/** Thousands-separated integer, e.g. "12,431" steps. */
export function formatCount(value: number | null): string {
  return value != null ? value.toLocaleString() : EM_DASH;
}

/** Kilojoules as kilocalories — Whoop reports energy in kJ, humans read kcal. */
export function kilojoulesToKcal(kj: number | null): string {
  return kj != null ? `${Math.round(kj / 4.184)} kcal` : EM_DASH;
}

/**
 * Coarse "3h ago" freshness label, or null when there is no timestamp.
 *
 * Returns null rather than EM_DASH so callers can omit the line entirely
 * instead of rendering an empty freshness indicator.
 */
export function timeAgo(iso: string | null): string | null {
  if (!iso) return null;
  const ms = Date.now() - new Date(iso).getTime();
  // A clock skew between device and server can put the push slightly in
  // the future; "just now" is truthful there, a negative age is not.
  if (ms < 60_000) return 'just now';
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`;
  return `${Math.floor(ms / 86_400_000)}d ago`;
}

// ── Whoop recovery scale ───────────────────────────────────────────────────
// Whoop's own banding: >=67 green, 34-66 yellow, <34 red. Defined once so
// the ring colour, the pill colour, and the pill text can never disagree.

export const RECOVERY_OPTIMAL_MIN = 67;
export const RECOVERY_MODERATE_MIN = 34;

export type RecoveryBand = 'none' | 'low' | 'moderate' | 'optimal';

export function recoveryBand(score: number | null): RecoveryBand {
  if (score == null) return 'none';
  if (score >= RECOVERY_OPTIMAL_MIN) return 'optimal';
  if (score >= RECOVERY_MODERATE_MIN) return 'moderate';
  return 'low';
}

export function recoveryColor(score: number | null): string {
  switch (recoveryBand(score)) {
    case 'optimal':
      return 'var(--status-ok)';
    case 'moderate':
      return 'var(--status-warn)';
    case 'low':
      return 'var(--status-danger)';
    default:
      return 'var(--text-muted)';
  }
}

export function recoveryLabel(score: number | null): string {
  switch (recoveryBand(score)) {
    case 'optimal':
      return 'Optimal';
    case 'moderate':
      return 'Moderate';
    case 'low':
      return 'Low';
    default:
      return 'No data';
  }
}
