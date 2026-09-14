import styles from './SkillsStatusPanel.module.css';

export type SkillsStatusVariant = 'empty' | 'filtered' | 'error';

export interface SkillsStatusPanelProps {
  variant: SkillsStatusVariant;
  /** Only used for `variant="error"` — the raw error message to surface. */
  detail?: string;
  /** Only used for `variant="error"` — retries the failed fetch. */
  onRetry?: () => void;
  /** Only used for `variant="filtered"` — clears active filters. */
  onClearFilters?: () => void;
}

const COPY: Record<SkillsStatusVariant, { glyph: string; title: string; body: string }> = {
  empty: {
    glyph: '◇',
    title: 'No skills registered yet',
    body: 'Skills sync automatically from .claude/skills/ on every backend deploy. Check back shortly, or trigger a deploy if this persists.',
  },
  filtered: {
    glyph: '⌁',
    title: 'No skills match these filters',
    body: 'Try enabling another category to widen the results.',
  },
  error: {
    glyph: '!',
    title: 'Could not load skills',
    body: 'The Skills tab could not reach the API.',
  },
};

/**
 * Single reusable panel for the Skills tab's empty, filtered-empty, and
 * error states — one component so the bold visual language (glyph badge,
 * uppercase eyebrow, centered layout) stays identical across all three
 * instead of drifting as ad-hoc `<div>`s.
 */
export default function SkillsStatusPanel({
  variant,
  detail,
  onRetry,
  onClearFilters,
}: SkillsStatusPanelProps) {
  const copy = COPY[variant];

  return (
    <div
      className={`${styles.panel} ${styles[variant]}`}
      role={variant === 'error' ? 'alert' : 'status'}
    >
      <span className={styles.glyph} aria-hidden="true">
        {copy.glyph}
      </span>
      <p className={styles.eyebrow}>{variant === 'error' ? 'Sync failed' : 'Skills'}</p>
      <h3 className={styles.title}>{copy.title}</h3>
      <p className={styles.body}>{copy.body}</p>
      {variant === 'error' && detail && <p className={styles.detail}>{detail}</p>}

      {variant === 'error' && onRetry && (
        <button type="button" className={styles.action} onClick={onRetry}>
          Retry
        </button>
      )}
      {variant === 'filtered' && onClearFilters && (
        <button type="button" className={styles.action} onClick={onClearFilters}>
          Show all categories
        </button>
      )}
    </div>
  );
}
