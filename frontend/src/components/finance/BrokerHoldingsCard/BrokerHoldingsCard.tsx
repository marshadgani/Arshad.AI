import { FinanceNotice } from '../FinanceNotice';
import { HoldingsTable } from '../HoldingsTable';
import type { BrokerHoldings } from '../../../types/finance';
import { formatShortDateTime } from '../../../utils/time';
import styles from './BrokerHoldingsCard.module.css';

export interface BrokerHoldingsCardProps {
  broker: BrokerHoldings;
}

export function BrokerHoldingsCard({ broker }: BrokerHoldingsCardProps) {
  const syncedAt = formatShortDateTime(broker.last_synced_at);
  const syncedLabel = syncedAt ? `as of ${syncedAt}` : null;

  return (
    <article className={styles.card}>
      <header className={styles.head}>
        <div>
          <h3 className={styles.name}>{broker.display_name}</h3>
          {/* Upstox sync() reads /v2/portfolio/long-term-holdings only. */}
          {broker.broker === 'upstox' && <span className={styles.subLabel}>Long-term holdings</span>}
        </div>
        {syncedLabel && <span className={styles.synced}>{syncedLabel}</span>}
      </header>

      {broker.needs_reauth ? (
        <FinanceNotice
          icon="⚠️"
          title={`Reconnect ${broker.display_name}`}
          description="This connection has expired. Reconnect to keep seeing live holdings."
          actionLabel="Reconnect"
          actionHref="/integrations"
        />
      ) : (
        <>
          {/* The server sanitises this field — services/finance/holdings.py
              ::_safe_error_message replaces Integration.last_error (raw
              upstream exception text, internal URLs, status codes) with
              generic copy before it ever reaches the wire, per
              .claude/rules/api.md. It is still used only as a boolean
              signal here, as defence in depth: the copy the user reads is
              owned by this component, so no future change on the wire side
              can turn this into a leak.

              The last successful snapshot stays on screen underneath: a
              transient provider 5xx sets status=error while
              config['holdings'] still holds good data, and blanking it
              would contradict the page's own never-blank policy. When
              there is no snapshot to fall back on (an empty card, e.g. the
              lookup itself failed) that wording would be a lie, hence the
              branch. */}
          {broker.error && (
            <p className={styles.error} role="status">
              {broker.holdings.length > 0
                ? 'Last sync failed — showing the most recent data we have.'
                : "Last sync failed — we couldn't load these holdings."}
            </p>
          )}
          {broker.holdings.length === 0 ? (
            <p className={styles.empty}>No holdings to display</p>
          ) : (
            <HoldingsTable
              holdings={broker.holdings}
              currency={broker.currency}
              holdingCount={broker.holding_count}
              truncated={broker.truncated}
            />
          )}
        </>
      )}
    </article>
  );
}
