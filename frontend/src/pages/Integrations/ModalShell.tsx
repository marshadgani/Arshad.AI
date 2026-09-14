import { useId } from 'react';
import type { ReactNode } from 'react';

import styles from './Integrations.module.css';

export interface ModalShellProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  /** Buttons rendered in the modal's action row. */
  actions: ReactNode;
  /**
   * 'danger' swaps the cyan focus/glow for the page's danger red
   * (DisconnectConfirmModal) so a destructive confirmation reads as
   * visually distinct from the "give us something" connect prompts,
   * which all use the default accent styling.
   */
  variant?: 'default' | 'danger';
}

/**
 * Backdrop + panel chrome shared by every modal on this page.
 *
 * The three modals each carried their own copy of the backdrop element,
 * the click-outside-to-close handler, and the stopPropagation guard that
 * keeps a click inside the panel from closing it. Three copies of a
 * dismissal rule is three chances for one of them to become subtly
 * undismissable.
 */
export default function ModalShell({
  title,
  onClose,
  children,
  actions,
  variant = 'default',
}: ModalShellProps) {
  const titleId = useId();
  return (
    <div className={styles.modalBackdrop} onClick={onClose}>
      <div
        className={variant === 'danger' ? `${styles.modal} ${styles.modalDanger}` : styles.modal}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <h3 id={titleId}>{title}</h3>
        {children}
        <div className={styles.modalActions}>{actions}</div>
      </div>
    </div>
  );
}
