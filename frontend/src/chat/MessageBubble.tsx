import { ReactNode } from 'react';

import styles from './MessageBubble.module.css';

export type BubbleRole = 'user' | 'assistant';

export interface MessageBubbleProps {
  role: BubbleRole;
  /** Appends the blinking caret — for text still arriving over the stream. */
  isStreaming?: boolean;
  children: ReactNode;
}

// The one place a chat bubble is drawn. Both the persisted transcript
// (MessageRow) and the in-flight stream (ChatTranscript) render through it,
// so a streaming bubble can never visually drift from its persisted form.
export function MessageBubble({ role, isStreaming = false, children }: MessageBubbleProps) {
  return (
    <div className={`${styles.bubble} ${styles[role]}`}>
      {children}
      {isStreaming && <span className={styles.caret} />}
    </div>
  );
}
