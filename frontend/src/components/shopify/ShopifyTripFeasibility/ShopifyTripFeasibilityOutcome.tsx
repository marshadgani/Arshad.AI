import type { TripFeasibilityResult, TripVerdict } from '../../../types/shopify';
import styles from './ShopifyTripFeasibility.module.css';

const VERDICT_LABEL: Record<TripVerdict, string> = {
  go: 'Go',
  'no-go': 'No-go',
  unknown: 'Unknown',
};

const VERDICT_CLASS: Record<TripVerdict, string> = {
  go: styles.go,
  'no-go': styles.noGo,
  unknown: styles.unknown,
};

/** Collect human-readable explanations for why the verdict is not a confident Go. */
function degradations(r: TripFeasibilityResult): { text: string; severe: boolean }[] {
  const out: { text: string; severe: boolean }[] = [];
  if (r.shopify_needs_reauth) out.push({ text: 'Reconnect Shopify to check stock.', severe: true });
  else if (!r.shopify_connected) out.push({ text: 'Shopify is not connected, so stock was not checked.', severe: false });
  if (r.calendar_needs_reauth) out.push({ text: 'Reconnect Google Calendar to check your schedule.', severe: true });
  else if (!r.calendar_connected) out.push({ text: 'Google Calendar is not connected, so your schedule was not checked.', severe: false });
  if (r.variants_truncated) out.push({ text: 'Only part of the product list was checked.', severe: false });
  if (r.orders_truncated) out.push({ text: 'Only part of the recent sales history was checked.', severe: false });
  if (r.calendar_truncated) out.push({ text: 'Your calendar has more events than could be checked.', severe: false });
  if (r.partial_failures.length > 0) {
    out.push({
      text: `Some data could not be fetched (${r.partial_failures.join(', ')}). Try again shortly.`,
      severe: false,
    });
  }
  return out;
}

export interface ShopifyTripFeasibilityOutcomeProps {
  result: TripFeasibilityResult;
}

export function ShopifyTripFeasibilityOutcome({ result }: ShopifyTripFeasibilityOutcomeProps) {
  const issues = degradations(result);
  // The backend validator (TripFeasibilityResponse._check_verdict_invariants)
  // already refuses a "go" with a conflict or a degraded source. This repeats
  // the rule so schema skew or a bad response can never show a green Go.
  const verdict: TripVerdict =
    result.verdict === 'go' && (issues.length > 0 || result.conflicts.length > 0)
      ? 'unknown'
      : result.verdict;
  const badgeClass = VERDICT_CLASS[verdict];

  return (
    <div aria-live="polite">
      <p className={styles.verdictRow}>
        Verdict: <span className={`${styles.badge} ${badgeClass}`}>{VERDICT_LABEL[verdict]}</span>
      </p>
      {issues.map((issue) => (
        <p
          key={issue.text}
          className={styles.caveat}
          role={issue.severe ? 'alert' : 'status'}
        >
          {issue.text}
        </p>
      ))}
      {result.conflicts.length > 0 && (
        <ul className={styles.list} aria-label="Conflicts">
          {result.conflicts.map((c, i) => (
            <li key={`${c.type}-${c.variant_id ?? c.event_start ?? i}`}>
              {c.type === 'stockout'
                ? `Stock runs out on ${c.projected_stockout_date}: ${c.variant_id}`
                : `Calendar: ${c.event_title} (${c.event_start})`}
            </li>
          ))}
        </ul>
      )}
      {result.all_day_events.length > 0 && (
        <div>
          <p className={styles.note}>All-day events in this window (not counted as conflicts):</p>
          <ul className={styles.list} aria-label="All-day events">
            {result.all_day_events.map((e) => (
              <li key={`${e.start_date}-${e.title}`}>{`${e.title} (${e.start_date})`}</li>
            ))}
          </ul>
        </div>
      )}
      {result.unavailable_sources.length > 0 && (
        <p className={styles.note}>
          Not checked:{' '}
          {result.unavailable_sources
            .map((s) => `${s.name.replace(/_/g, ' ')} (${s.reason.replace(/_/g, ' ')})`)
            .join(', ')}
          .
        </p>
      )}
    </div>
  );
}
