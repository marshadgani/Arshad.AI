import ModalShell from './ModalShell';
import styles from './Integrations.module.css';
import type { IntegrationItem } from './types';

export interface ConnectPromptModalProps {
  item: IntegrationItem;
  value: string;
  error: string | null;
  busy: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onClose: () => void;
}

/**
 * Extra-input prompt shown before starting OAuth for any provider that
 * declares `connect_prompt` (e.g. Shopify's *.myshopify.com domain).
 * Driven entirely by the descriptor — no slug special-casing, so a future
 * provider that needs an account identifier gets this screen for free.
 */
export default function ConnectPromptModal({
  item,
  value,
  error,
  busy,
  onChange,
  onSubmit,
  onClose,
}: ConnectPromptModalProps) {
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
            {busy ? 'Connecting…' : 'Connect'}
          </button>
        </>
      }
    >
      <p className={styles.modalDesc}>
        Enter your {item.connect_prompt?.label ?? 'store domain'}. You'll be redirected
        to Shopify to approve access.
      </p>
      <input
        type="text"
        className={styles.modalInput}
        placeholder={item.connect_prompt?.placeholder ?? ''}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoFocus
      />
      {error && <div className={styles.modalErr}>{error}</div>}
    </ModalShell>
  );
}
