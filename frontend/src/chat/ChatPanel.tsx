import { useEffect, useRef } from 'react';

import { ChatComposer } from './ChatComposer';
import { MessageRow } from './MessageRow';
import { ToolCallChip } from './ToolCallChip';
import styles from './ChatPanel.module.css';
import { useChatHistory } from './useChatHistory';
import { useChatStream } from './useChatStream';

export interface ChatPanelProps {
  sessionId: string;
}

// Composition root for the chat surface: it wires persisted history
// (useChatHistory) to the live stream (useChatStream) and renders the four
// states. Transport, draft state and message markup live in siblings.
export function ChatPanel({ sessionId }: ChatPanelProps) {
  const stream = useChatStream(sessionId);
  const history = useChatHistory(sessionId);
  const scrollerRef = useRef<HTMLDivElement>(null);

  const hasStreamOutput = Boolean(stream.assistantText) || stream.toolCalls.length > 0;

  // Autoscroll on new content.
  useEffect(() => {
    scrollerRef.current?.scrollTo({
      top: scrollerRef.current.scrollHeight,
      behavior: 'smooth',
    });
  }, [history.messages.length, stream.assistantText, stream.toolCalls.length]);

  // Once streaming finishes, pull the canonical rows so the optimistic user
  // message and the transient assistant text are replaced by persisted ones.
  useEffect(() => {
    if (stream.isStreaming || !hasStreamOutput) return;
    history.refresh();
    // Only the stream *ending* should trigger this — re-running as each token
    // arrives would refetch the whole conversation per delta.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream.isStreaming, sessionId]);

  const handleSend = (text: string) => {
    history.appendOptimistic(text);
    void stream.send(text);
  };

  const showEmptyState =
    !history.isLoading &&
    !history.error &&
    history.messages.length === 0 &&
    !stream.isStreaming &&
    !hasStreamOutput;

  return (
    <section className={styles.panel}>
      <div className="sr-only" aria-live="polite">
        {stream.isStreaming
          ? 'Assistant is responding…'
          : stream.error
            ? `Error: ${stream.error}`
            : ''}
      </div>

      <div className={styles.scroller} ref={scrollerRef}>
        {history.isLoading && (
          <div className={styles.loadingState} role="status">
            <span className={styles.spinner} aria-hidden="true" />
            Loading conversation…
          </div>
        )}

        {history.error && (
          <div className={styles.historyError} role="alert">
            <span>{history.error}</span>
            <button type="button" className={styles.retryButton} onClick={history.reload}>
              Retry
            </button>
          </div>
        )}

        {showEmptyState && (
          <div className={styles.emptyState}>
            <span className={styles.emptyGlyph} aria-hidden="true">✶</span>
            <p>Ask Arshad.AI anything — calendar, email, GitHub, or just talk.</p>
          </div>
        )}

        {!history.isLoading &&
          !history.error &&
          history.messages.map((m) => <MessageRow key={m.id} message={m} />)}

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
          <div className={styles.error} role="alert">
            <strong>error:</strong> {stream.error}
          </div>
        )}
      </div>

      <ChatComposer disabled={stream.isStreaming} onSubmit={handleSend} />
    </section>
  );
}
