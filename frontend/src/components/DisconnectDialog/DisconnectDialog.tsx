import { useEffect, useRef } from 'react';

import Scrim from '../Scrim';
import styles from './DisconnectDialog.module.css';

export type RevocationKind = 'revokes' | 'no_revoke' | 'no_credential';

export interface DisconnectDialogProps {
  provider: {
    display_name: string;
    revocation_kind: RevocationKind;
  };
  onConfirm: () => void;
  onCancel: () => void;
  isLoading: boolean;
}

const COPY: Record<RevocationKind, (name: string) => string> = {
  revokes: (name) => `Stored credentials will be removed and access revoked with ${name}.`,
  no_revoke: (name) =>
    `Stored credentials will be removed from Arshad.AI. ${name} does not offer a revoke API — you may also want to revoke access in your ${name} account settings.`,
  no_credential: (name) =>
    `This stops ${name} syncing. Your sign-in is unaffected — revoke access in your ${name} account settings if needed.`,
};

// Replaces the plain window.confirm() this dialog used to be — that copy
// said "Stored credentials will be removed" unconditionally, which was
// false for every provider except Apple Health. Copy here is keyed on
// revocation_kind so the promise made is the promise the backend keeps.
export default function DisconnectDialog({
  provider,
  onConfirm,
  onCancel,
  isLoading,
}: DisconnectDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    confirmRef.current?.focus();
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onCancel]);

  const describe = COPY[provider.revocation_kind] ?? COPY.no_revoke;

  return (
    <>
      <Scrim label="Close disconnect dialog" onDismiss={onCancel} />
      <div
        ref={dialogRef}
        className={styles.dialog}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="disconnect-dialog-title"
        aria-describedby="disconnect-dialog-desc"
      >
        <h3 id="disconnect-dialog-title">Disconnect {provider.display_name}?</h3>
        <p id="disconnect-dialog-desc" className={styles.desc}>
          {describe(provider.display_name)}
        </p>
        <div className={styles.actions}>
          <button type="button" className={styles.secondary} onClick={onCancel}>
            Cancel
          </button>
          <button
            ref={confirmRef}
            type="button"
            className={styles.danger}
            onClick={onConfirm}
            disabled={isLoading}
          >
            {isLoading ? 'Disconnecting…' : 'Disconnect'}
          </button>
        </div>
      </div>
    </>
  );
}
