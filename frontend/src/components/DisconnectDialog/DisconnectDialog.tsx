import { useEffect, useId, useRef } from 'react';

import Scrim from '../Scrim';
import styles from './DisconnectDialog.module.css';

export type RevocationKind = 'revokes' | 'no_revoke' | 'no_credential';

export interface DisconnectDialogProps {
  /** Human-readable provider name, e.g. "GitHub". */
  displayName: string;
  /**
   * Mirrors backend/src/integrations/base.py's `revocation_kind`
   * (see backend/src/integrations/DECISION.md). Drives both the copy and
   * the tone of this dialog so the promise it makes is never stronger than
   * what disconnect() actually does for that provider.
   */
  revocationKind: RevocationKind;
  /** True while the disconnect request is in flight. */
  isSubmitting: boolean;
  /** Non-null after a failed disconnect attempt — renders a retry state. */
  error: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}

const REVOCATION_META: Record<
  RevocationKind,
  { tone: 'danger' | 'warn' | 'neutral'; badge: string; icon: string; body: (name: string) => string }
> = {
  revokes: {
    tone: 'danger',
    badge: 'Full revoke',
    icon: '⏻',
    body: (name) =>
      `Stored credentials will be deleted here and the access grant will be revoked with ${name} directly — the third-party session ends immediately.`,
  },
  no_revoke: {
    tone: 'warn',
    badge: 'Manual step required',
    icon: '⚠',
    body: (name) =>
      `Stored credentials will be deleted here. ${name} has no revocation API, so the key stays valid on ${name}'s side until you remove it from your ${name} dashboard.`,
  },
  no_credential: {
    tone: 'neutral',
    badge: 'Nothing stored',
    icon: 'ⓘ',
    body: (name) =>
      `This stops ${name} syncing. Your sign-in is unaffected — no separate credential is stored for ${name}, so revoke access in your ${name} account settings if needed.`,
  },
};

function confirmLabel(error: string | null): string {
  return error ? 'Retry disconnect' : 'Disconnect';
}

/**
 * Replaces a plain window.confirm() disconnect prompt. The three
 * revocation_kind variants promise genuinely different outcomes (full
 * revoke vs. local-only delete vs. nothing stored at all) — a single
 * generic "Are you sure?" cannot carry that distinction, and a native
 * confirm() can't render tone, retry state, or a busy indicator.
 *
 * Reusable across any provider: nothing here is slug-specific.
 */
export function DisconnectDialog({
  displayName,
  revocationKind,
  isSubmitting,
  error,
  onConfirm,
  onCancel,
}: DisconnectDialogProps) {
  const meta = REVOCATION_META[revocationKind];
  const titleId = useId();
  const descId = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    cancelRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isSubmitting) onCancel();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isSubmitting, onCancel]);

  return (
    <div className={styles.wrap}>
      <Scrim
        label={`Cancel disconnecting ${displayName}`}
        onDismiss={() => {
          if (!isSubmitting) onCancel();
        }}
      />
      <div
        className={`${styles.dialog} ${styles[meta.tone]}`}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descId}
      >
        <span className={`${styles.badge} ${styles[meta.tone]}`}>
          <span aria-hidden="true">{meta.icon}</span> {meta.badge}
        </span>
        <h2 id={titleId} className={styles.title}>
          Disconnect {displayName}?
        </h2>
        <p id={descId} className={styles.body}>
          {meta.body(displayName)}
        </p>

        {error && (
          <div className={styles.errorBanner} role="alert">
            {error}
          </div>
        )}

        <div className={styles.actions}>
          <button
            ref={cancelRef}
            type="button"
            className={styles.cancel}
            onClick={onCancel}
            disabled={isSubmitting}
          >
            Cancel
          </button>
          <button
            type="button"
            className={`${styles.confirm} ${styles[meta.tone]}`}
            onClick={onConfirm}
            disabled={isSubmitting}
            aria-busy={isSubmitting}
          >
            {isSubmitting ? (
              <>
                <span className={styles.spinner} aria-hidden="true" />
                Disconnecting…
              </>
            ) : (
              confirmLabel(error)
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
