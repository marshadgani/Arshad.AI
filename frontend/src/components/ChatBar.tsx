import { useState } from 'react';
import styles from './ChatBar.module.css';

export interface ChatBarProps {}

export default function ChatBar(_: ChatBarProps) {
  const [value, setValue] = useState('');

  return (
    <footer className={styles.chatbar}>
      <div className={styles.wrap}>
        <span className={styles.spark}>✶</span>
        <input
          className={styles.input}
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder='Ask Arshad.AI — try "summarise unread emails" or "what\'s on my calendar tomorrow?"'
        />
        <button
          className={styles.send}
          onClick={() => {
            // mock — wired to Anthropic SDK in a future session
            console.log('chat:', value);
            setValue('');
          }}
        >
          Send
        </button>
      </div>
      <div className={styles.hint}>
        <kbd>⌘</kbd> + <kbd>K</kbd> focus from anywhere · <kbd>⇧</kbd> + <kbd>↩</kbd> newline · powered by Claude (mock)
      </div>
    </footer>
  );
}
