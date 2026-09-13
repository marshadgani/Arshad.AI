import type { ReactNode } from 'react';

import { useFinanceHoldings } from '../../../hooks/useFinanceHoldings';
import { BrokerHoldingsCard } from '../BrokerHoldingsCard';
import { FinanceNotice } from '../FinanceNotice';
import styles from './BrokerageHoldings.module.css';

const TITLE = 'Brokerage Holdings';

interface SectionProps {
  /** Marks the whole section busy while the first load is in flight. */
  busy?: boolean;
  /** Rendered on the heading row — only the loaded state has an action. */
  action?: ReactNode;
  children: ReactNode;
}

/**
 * The section frame every state renders inside.
 *
 * Extracted because all four branches below repeated it verbatim, which
 * meant the heading text, the landmark and its class names each had four
 * places to drift apart. With the frame owned here, each branch states
 * only what is different about its state.
 */
function Section({ busy, action, children }: SectionProps) {
  return (
    <section className={styles.section} aria-busy={busy || undefined}>
      {action ? (
        <header className={styles.head}>
          <h2 className={styles.heading}>{TITLE}</h2>
          {action}
        </header>
      ) : (
        <h2 className={styles.heading}>{TITLE}</h2>
      )}
      {children}
    </section>
  );
}

/**
 * Real Upstox / Zerodha Kite holdings, mounted on both /finance and /stocks.
 *
 * State router only -- loading (skeleton), error (banner + retry),
 * disconnected (notice with a link to /integrations), then one
 * BrokerHoldingsCard per connected broker. Loading/error gate on `!data` so
 * a later refetch never blanks an already-rendered page.
 */
export function BrokerageHoldings() {
  const { data, isLoading, error, refetch, syncAll, isSyncing, syncError } = useFinanceHoldings();

  if (isLoading && !data) {
    return (
      <Section busy>
        <p className={styles.status}>Loading brokerage holdings…</p>
        <div className={styles.grid} aria-hidden="true">
          <div className={styles.skeletonCard} />
          <div className={styles.skeletonCard} />
        </div>
      </Section>
    );
  }

  if (error && !data) {
    return (
      <Section>
        <p className={styles.errorBanner}>
          Failed to load brokerage holdings.{' '}
          <button type="button" className={styles.retry} onClick={refetch}>
            Retry
          </button>
        </p>
      </Section>
    );
  }

  if (!data?.connected) {
    return (
      <Section>
        <FinanceNotice
          icon="📈"
          title="No brokerage account connected"
          description="Connect Upstox or Zerodha Kite to see your real holdings here."
          actionLabel="Connect a broker"
          actionHref="/integrations"
        />
      </Section>
    );
  }

  return (
    <Section
      action={
        <button
          type="button"
          className={styles.syncButton}
          onClick={syncAll}
          disabled={isSyncing}
          aria-busy={isSyncing}
        >
          {isSyncing ? 'Syncing…' : 'Sync now'}
        </button>
      }
    >
      {syncError && <p className={styles.syncWarning}>{syncError.message}</p>}
      <div className={styles.grid}>
        {data.brokers.map((broker) => (
          <BrokerHoldingsCard key={broker.broker} broker={broker} />
        ))}
      </div>
    </Section>
  );
}
