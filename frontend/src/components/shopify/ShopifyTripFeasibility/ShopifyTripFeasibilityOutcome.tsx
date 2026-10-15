import type { TripConflict, TripFeasibilityResult, TripVerdict } from '../../../types/shopify';
import styles from './ShopifyTripFeasibility.module.css';

const VERDICT_LABEL: Record<TripVerdict, string> = {
  go: 'Go',
  'no-go': 'No-go',
  unknown: 'Unknown',
};

const PROVIDER_LABEL = { render: 'Render', supabase: 'Supabase' } as const;

function conflictKey(c: TripConflict, i: number): string {
  if (c.type === 'infrastructure') return `infra-${c.provider}-${c.infra_name}-${i}`;
  if (c.type === 'calendly_event') return `calendly-${c.calendly_event_start}-${i}`;
  return `${c.type}-${c.variant_id ?? c.event_start ?? i}`;
}

function conflictText(c: TripConflict): string {
  switch (c.type) {
    case 'stockout':
      return `Stock runs out on ${c.projected_stockout_date}: ${c.variant_id}`;
    case 'calendar_event':
      return `Calendar: ${c.event_title} (${c.event_start})`;
    case 'calendly_event':
      return `Calendly: ${c.calendly_event_title} (${c.calendly_event_start})`;
    case 'infrastructure':
      return `${PROVIDER_LABEL[c.provider]}: ${c.infra_name} is ${c.infra_state}`;
  }
}

const VERDICT_CLASS: Record<TripVerdict, string> = {
  go: styles.go,
  'no-go': styles.noGo,
  unknown: styles.unknown,
};

interface Degradation {
  text: string;
  severe: boolean;
  href?: string;
  linkText?: string;
}

/** Collect human-readable explanations for why the verdict is not a confident Go. */
function degradations(r: TripFeasibilityResult): Degradation[] {
  const out: Degradation[] = [];
  if (r.shopify_needs_reauth) out.push({ text: 'Reconnect Shopify to check stock.', severe: true });
  else if (!r.shopify_connected) out.push({ text: 'Shopify is not connected, so stock was not checked.', severe: false });
  if (r.calendar_needs_reauth) out.push({ text: 'Reconnect Google Calendar to check your schedule.', severe: true });
  else if (!r.calendar_connected) out.push({ text: 'Google Calendar is not connected, so your schedule was not checked.', severe: false });
  if (r.calendly_needs_reauth) out.push({ text: 'Your Calendly token needs to be reconnected. Update it from the Integrations page.', severe: true });
  else if (!r.calendly_connected) out.push({
    text: 'Connect Calendly from the Integrations page to check your meetings.',
    severe: true,
    href: '/integrations',
    linkText: 'Integrations',
  });
  else if (r.calendly_truncated) out.push({ text: 'Too many Calendly meetings to check (truncated); some may have been missed.', severe: true });
  if (r.variants_truncated) out.push({ text: 'Only part of the product list was checked.', severe: false });
  if (r.orders_truncated) out.push({ text: 'Only part of the recent sales history was checked.', severe: false });
  if (r.calendar_truncated) out.push({ text: 'Your calendar has more events than could be checked.', severe: false });
  if (r.render_connected) {
    if (r.render_sync_error) out.push({ text: 'The last Render sync failed, so service health is unknown. Re-sync Render from Integrations.', severe: true });
    else if (r.render_needs_sync) out.push({ text: 'Render has never been synced, so service health was not checked. Sync it from Integrations.', severe: true });
    else if (r.render_stale) out.push({ text: 'The Render snapshot is more than 24 hours old, so service health is unconfirmed. Re-sync Render from Integrations.', severe: true });
    if (r.render_truncated) out.push({ text: 'Only the first 10 Render services were checked.', severe: true });
  }
  if (r.supabase_connected) {
    if (r.supabase_sync_error) out.push({ text: 'The last Supabase sync failed, so project health is unknown. Re-sync Supabase from Integrations.', severe: true });
    else if (r.supabase_needs_sync) out.push({ text: 'Supabase has never been synced, so project health was not checked. Sync it from Integrations.', severe: true });
    else if (r.supabase_stale) out.push({ text: 'The Supabase snapshot is more than 24 hours old, so project health is unconfirmed. Re-sync Supabase from Integrations.', severe: true });
  }
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
  const notChecked = result.unavailable_sources;

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
          {issue.href && <> &middot; <a href={issue.href}>{issue.linkText}</a></>}
        </p>
      ))}
      {result.conflicts.length > 0 && (
        <ul className={styles.list} aria-label="Conflicts">
          {result.conflicts.map((c, i) => (
            <li key={conflictKey(c, i)}>{conflictText(c)}</li>
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
      {notChecked.length > 0 && (
        <p className={styles.note}>
          Not checked:{' '}
          {notChecked
            .map((s) => `${s.name.replace(/_/g, ' ')} (${s.reason.replace(/_/g, ' ')})`)
            .join(', ')}
          .
        </p>
      )}
    </div>
  );
}
