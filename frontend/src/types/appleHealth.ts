/**
 * Wire type for GET /api/v1/apple-health/dashboard.
 *
 * Mirrors AppleHealthSnapshot in backend/src/schemas/apple_health.py, and
 * sits beside types/whoop.ts for the same reason: the shape is shared by a
 * hook, a card, and that card's tests, so it belongs to the module boundary
 * rather than to whichever consumer happened to declare it first.
 *
 * Every metric is nullable because the user's Shortcut decides what to
 * send — a device with no VO2max reading omits it, and out-of-range values
 * are coerced to null server-side. Cards must render "—", not crash.
 */
export interface AppleHealthSnapshot {
  connected: boolean;
  /** True when no push has arrived within the server's cache window: the
   * Shortcut has likely stopped running, rather than the data being wrong. */
  stale: boolean;
  resting_heart_rate: number | null;
  heart_rate_variability_ms: number | null;
  sleep_hours: number | null;
  active_energy_kcal: number | null;
  steps: number | null;
  vo2_max: number | null;
  recorded_at: string | null;
  received_at: string | null;
}

/**
 * Fields consulted to decide "has this connection produced any reading
 * yet?", i.e. whether to show the waiting-for-first-push state.
 *
 * BEHAVIOUR PRESERVED VERBATIM — heart_rate_variability_ms is deliberately
 * absent. AppleHealthCard's original predicate was a five-term boolean
 * written out twice (once plain, once negated) that omitted HRV, so a
 * snapshot carrying only an HRV reading renders as "waiting for the first
 * push". That looks like an oversight rather than a decision, but changing
 * it here would be a behaviour change smuggled into a restructure. Lifted
 * as-is, in one place, so the two copies can no longer disagree with each
 * other — and so the omission is now visible instead of buried in JSX.
 *
 * FLAGGED for the bug-fix stage: confirm whether HRV should count, and fix
 * it as its own change with its own test.
 */
export const APPLE_HEALTH_PRESENCE_KEYS = [
  'resting_heart_rate',
  'sleep_hours',
  'active_energy_kcal',
  'steps',
  'vo2_max',
] as const;

export function hasAnyMetric(snapshot: AppleHealthSnapshot): boolean {
  return APPLE_HEALTH_PRESENCE_KEYS.some((key) => snapshot[key] != null);
}
