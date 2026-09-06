import styles from './ChatPanel.module.css';
import type { PersistedMessage } from './types';

export interface MessageRowProps {
  message: PersistedMessage;
}

export function MessageRow({ message }: MessageRowProps) {
  if (message.role === 'user') {
    return <div className={`${styles.bubble} ${styles.user}`}>{message.content.text}</div>;
  }
  if (message.role === 'assistant') {
    return <div className={`${styles.bubble} ${styles.assistant}`}>{message.content.text}</div>;
  }
  if (message.role === 'tool_use') {
    return (
      <div className={styles.toolUseInline}>
        <code>{message.content.tool ?? '(tool)'}</code>
      </div>
    );
  }
  // tool_result rows are not rendered separately; the assistant message
  // immediately following them carries the user-visible response.
  return null;
}
