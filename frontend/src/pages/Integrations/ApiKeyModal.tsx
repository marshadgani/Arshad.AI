import ModalShell from './ModalShell';
import styles from './Integrations.module.css';
import type { IntegrationItem } from './types';

export interface ApiKeyModalProps {
  item: IntegrationItem;
  value: string;
  error: string | null;
  busy: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onClose: () => void;
}

/** Credential prompt for project_apikey providers. */
export default function ApiKeyModal({
  item,
  value,
  error,
  busy,
  onChange,
  onSubmit,
  onClose,
}: ApiKeyModalProps) {
  return (
    <ModalShell
      title={`Connect ${item.display_name}`}
      onClose={onClose}
      actions={
        <>
          <button type="button" className={styles.secondary} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className={styles.primary}
            onClick={onSubmit}
            disabled={busy}
          >
            {busy ? 'Validating…' : 'Connect'}
          </button>
        </>
      }
    >
      <p className={styles.modalDesc}>
        Paste your API key. It will be encrypted at rest with AES-GCM and only the first
        6 characters shown back.
      </p>
      <input
        type="password"
        className={styles.modalInput}
        placeholder="API key"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoFocus
      />
      {error && <div className={styles.modalErr}>{error}</div>}
    </ModalShell>
  );
}
