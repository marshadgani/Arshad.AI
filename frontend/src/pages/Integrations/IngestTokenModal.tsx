import { useState } from 'react';

import ModalShell from './ModalShell';
import styles from './Integrations.module.css';
import type { IntegrationItem } from './types';

export interface IngestTokenModalProps {
  item: IntegrationItem;
  /** One-time-display secret. Never logged, stored, or put in a URL. */
  token: string;
  onClose: () => void;
}

const COPIED_FEEDBACK_MS = 2000;

/**
 * Shows the one-time ingest token returned by a personal_push provider's
 * connect() (e.g. Apple Health). The "copied" flag is local state here
 * rather than page state: it is meaningless once this modal closes, and
 * keeping it on the page meant an unrelated re-render could clear it.
 */
export default function IngestTokenModal({
  item,
  token,
  onClose,
}: IngestTokenModalProps) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(token);
      setCopied(true);
      setTimeout(() => setCopied(false), COPIED_FEEDBACK_MS);
    } catch {
      // Clipboard API can be blocked — token remains visible/selectable.
    }
  };

  return (
    <ModalShell
      title={`${item.display_name} sync token`}
      onClose={onClose}
      actions={
        <>
          <button type="button" className={styles.secondary} onClick={copy}>
            {copied ? 'Copied' : 'Copy'}
          </button>
          <button type="button" className={styles.primary} onClick={onClose}>
            Done — I've saved it
          </button>
        </>
      }
    >
      <p className={styles.modalDesc}>
        This token is shown once. Save it now — it's required to configure the push
        (e.g. an iOS Shortcut) that sends data to Arshad.AI.
      </p>
      <div className={styles.modalInput} style={{ userSelect: 'all' }}>
        {token}
      </div>
    </ModalShell>
  );
}
