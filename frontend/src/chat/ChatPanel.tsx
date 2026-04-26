import { useEffect, useRef, useState } from 'react';

import { ToolCallChip } from './ToolCallChip';
import styles from './ChatPanel.module.css';
import { useChatStream } from './useChatStream';

interface PersistedMessage {
  id: string;
  role: string;
  content: { text?: string; tool?: string; output?: unknown; is_error?: boolean };
  created_at: string | null;
}

export function ChatPanel({ sessionId }: { sessionId: string }) {
  const stream = useChatStream(sessionId);
  const [history, setHistory] = useState<PersistedMessage[]>([]);
  const [draft, setDraft] = useState('');
  const scrollerRef = useRef<HTMLDivElement>(null);

  // Load persisted history when session changes.
  useEffect(() => {
    let active = true;
    fetch(`/api/v1/chat/sessions/${sessionId}/messages`, {
      headers: { Authorization: `Bearer ${localStorage.getItem('arshad.ai:jwt') ?? ''}` },
    })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((body) => {
        if (active) setHistory((body.data ?? []) as PersistedMessage[]);
      })
      .catch(() => {
        if (active) setHistory([]);
      });
    return () => {
      active = false;
    };
  }, [sessionId]);

  // Autoscroll on new content.
  useEffect(() => {
    scrollerRef.current?.scrollTo({
      top: scrollerRef.current.scrollHeight,
      behavior: 'smooth',
    });
  }, [history.length, stream.assistantText, stream.toolCalls.length]);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!draft.trim() || stream.isStreaming) return;
    const text = draft;
    setDraft('');
    // Optimistically append the user message.
    setHistory((h) => [
      ...h,
      {
        id: `optimistic-${Date.now()}`,
        role: 'user',
        content: { text },
        created_at: null,
      },
    ]);
    void stream.send(text);
  };

  // After streaming finishes, refresh history so the assistant message is canonical.
  useEffect(() => {
    if (stream.isStreaming) return;
    if (!stream.assistantText && stream.toolCalls.length === 0) return;
    fetch(`/api/v1/chat/sessions/${sessionId}/messages`, {
      headers: { Authorization: `Bearer ${localStorage.getItem('arshad.ai:jwt') ?? ''}` },
    })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((body) => setHistory((body.data ?? []) as PersistedMessage[]))
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream.isStreaming, sessionId]);

  return (
    <section className={styles.panel}>
      <div className={styles.scroller} ref={scrollerRef}>
        {history.map((m) => (
          <MessageRow key={m.id} message={m} />
        ))}

        {stream.isStreaming && (
          <div className={styles.streamingBlock}>
            {stream.intent && <div className={styles.intent}>intent: {stream.intent}</div>}
            {stream.toolCalls.map((tc) => (
              <ToolCallChip key={tc.id} tool={tc} />
            ))}
            {stream.assistantText && (
              <div className={`${styles.bubble} ${styles.assistant}`}>
                {stream.assistantText}
                <span className={styles.caret} />
              </div>
            )}
          </div>
        )}

        {stream.error && (
          <div className={styles.error}>
            <strong>error:</strong> {stream.error}
          </div>
        )}
      </div>

      <form className={styles.composer} onSubmit={onSubmit}>
        <input
          className={styles.input}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask anything…"
          disabled={stream.isStreaming}
        />
        <button
          type="submit"
          className={styles.send}
          disabled={stream.isStreaming || !draft.trim()}
        >
          {stream.isStreaming ? 'Streaming…' : 'Send'}
        </button>
      </form>
    </section>
  );
}

function MessageRow({ message }: { message: PersistedMessage }) {
  if (message.role === 'user') {
    return (
      <div className={`${styles.bubble} ${styles.user}`}>{message.content.text}</div>
    );
  }
  if (message.role === 'assistant') {
    return (
      <div className={`${styles.bubble} ${styles.assistant}`}>{message.content.text}</div>
    );
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
