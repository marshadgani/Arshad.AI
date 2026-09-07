import type { ReactNode } from 'react';
import styles from './KpiCard.module.css';

export interface KpiCardProps {
  label: string;
  value: string | number | null;
  hint?: string | null;
  state: 'loading' | 'ok' | 'empty' | 'unavailable';
  docsHref?: string | null;
  /** Single glyph/emoji rendered in the accent chip — purely decorative. */
  icon?: ReactNode;
}

/**
 * A single KPI tile on the Shopify dashboard.
 *
 * Four distinct visual states, per the design brief:
 *   loading     — shimmering skeleton, no stale/zero value ever shown
 *   ok          — full value in the commerce-accent display face
 *   empty       — dash + "no data yet" framing, not an error
 *   unavailable — plan-gated metric, framed as informational, not broken
 */
export function KpiCard({ label, value, hint, state, docsHref, icon }: KpiCardProps) {
  const isLoading = state === 'loading';

  return (
    <div
      className={`${styles.card} ${styles[state]}`}
      role="group"
      aria-label={label}
      aria-busy={isLoading}
    >
      <div className={styles.top}>
        <span className={styles.label}>{label}</span>
        {icon && (
          <span className={styles.iconChip} aria-hidden="true">
            {icon}
          </span>
        )}
      </div>

      {isLoading ? (
        <div className={styles.skeleton} aria-hidden="true">
          <span className={styles.skeletonBar} />
        </div>
      ) : state === 'unavailable' ? (
        <div className={styles.unavailable}>
          <span className={styles.lockIcon} aria-hidden="true">
            ⋯
          </span>
          Not available on this plan
          {docsHref && (
            <a
              href={docsHref}
              target="_blank"
              rel="noreferrer"
              className={styles.docsLink}
            >
              Learn more
            </a>
          )}
        </div>
      ) : (
        <div className={styles.value}>{value ?? '—'}</div>
      )}

      {hint && !isLoading && state !== 'unavailable' && (
        <div className={styles.hint}>{hint}</div>
      )}
    </div>
  );
}
