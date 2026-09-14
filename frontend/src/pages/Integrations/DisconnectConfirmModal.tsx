import ModalShell from './ModalShell';
import styles from './Integrations.module.css';
import type { IntegrationItem } from './types';

export interface DisconnectConfirmModalProps {
  item: IntegrationItem;
  /** True while the revoke request is in flight. */
  submitting: boolean;
  /** Set when the previous attempt failed — null in the initial confirm state. */
  error: string | null;
  onConfirm: () => void;
  onClose: () => void;
}

/**
 * Destructive-action confirmation for disconnecting an integration.
 *
 * Deliberately styled apart from the other three modals on this page
 * (ApiKeyModal, ConnectPromptModal, IngestTokenModal): those are all
 * "give us something" prompts in the page's cyan accent, this one is
 * "we are about to destroy something" — danger red border/glow
 * (var(--status-danger), matching .errBanner elsewhere on this page)
 * instead of the cyan focus ring, so a user skimming past won't confuse
 * it with a routine connect step.
 *
 * Three of this component's states map onto real request lifecycle, not
 * decoration:
 *   - content — the confirm prompt itself (default)
 *   - loading — `submitting`, disables both buttons and shows a spinner
 *     so a slow upstream revoke (e.g. a provider's OAuth revocation
 *     endpoint) can't be double-submitted
 *   - error — `error`, shown inline with a "Try again" affordance rather
 *     than closing and losing context, because base.py's disconnect()
 *     rolls back and re-raises on a failed local delete — the user needs
 *     to retry the same action, not start over
 * There is no meaningful "empty" state for a single-item confirmation —
 * IntegrationCard never renders this component without an `item`.
 *
 * The second paragraph is `item.upstream_revocation.detail`, written by
 * the provider itself (backend/src/integrations/base.py) and rendered
 * verbatim. This modal deliberately does NOT compose its own sentence
 * about what happens at the third party: it used to, claiming
 * "credentials will be revoked with the provider" for all 44 providers
 * when not one of them revoked anything upstream. Only the provider
 * knows whether it can revoke, and a dozen of them still cannot — for
 * those, `detail` tells the user the manual step (remove the app in
 * Spotify's settings, delete the key in Render's dashboard) instead of
 * leaving them believing it was handled.
 */
export default function DisconnectConfirmModal({
  item,
  submitting,
  error,
  onConfirm,
  onClose,
}: DisconnectConfirmModalProps) {
  return (
    <ModalShell
      title={`Disconnect ${item.display_name}?`}
      onClose={onClose}
      variant="danger"
      actions={
        <>
          <button
            type="button"
            className={styles.secondary}
            onClick={onClose}
            disabled={submitting}
          >
            Cancel
          </button>
          <button
            type="button"
            className={styles.danger}
            onClick={onConfirm}
            disabled={submitting}
            aria-busy={submitting}
          >
            {submitting && <span className={styles.spinner} aria-hidden="true" />}
            {submitting ? 'Revoking…' : error ? 'Try again' : 'Disconnect'}
          </button>
        </>
      }
    >
      <p className={styles.modalDesc}>
        Stored credentials for {item.display_name} will be permanently deleted from
        Arshad.AI — this cannot be undone. Your Arshad.AI sign-in is not affected.
      </p>
      <p
        className={
          item.upstream_revocation.supported ? styles.modalDesc : styles.modalNote
        }
      >
        {item.upstream_revocation.detail}
      </p>
      {error && (
        <div className={styles.modalErr} role="alert">
          {error}
        </div>
      )}
    </ModalShell>
  );
}
