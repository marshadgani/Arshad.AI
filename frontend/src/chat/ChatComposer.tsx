import { FormEvent, useState } from 'react';

import styles from './ChatComposer.module.css';

export interface ChatComposerProps {
  disabled: boolean;
  onSubmit: (text: string) => void;
  /**
   * Seeds the draft on mount only (e.g. from TopBar's Quick Capture). A
   * later change to this prop is intentionally ignored — re-seeding on
   * every render would clobber whatever the user has since typed.
   */
  initialDraft?: string;
}

// Owns the draft only. It does not know about sessions, streaming or
// history — it hands a non-empty string upward and clears itself.
export function ChatComposer({ disabled, onSubmit, initialDraft }: ChatComposerProps) {
  const [draft, setDraft] = useState(initialDraft ?? '');
  const canSend = !disabled && draft.trim().length > 0;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!canSend) return;
    setDraft('');
    onSubmit(draft);
  };

  return (
    <form className={styles.composer} onSubmit={handleSubmit}>
      <label htmlFor="chat-composer-input" className="sr-only">
        Message
      </label>
      <input
        id="chat-composer-input"
        className={styles.input}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder="Ask anything…"
        disabled={disabled}
      />
      <button type="submit" className={styles.send} disabled={!canSend}>
        {disabled ? 'Streaming…' : 'Send'}
      </button>
    </form>
  );
}
