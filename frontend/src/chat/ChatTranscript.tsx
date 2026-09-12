import { useRef } from 'react';

import { MessageBubble } from './MessageBubble';
import { MessageRow } from './MessageRow';
import { ToolCallChip } from './ToolCallChip';
import { useAutoScroll } from '../hooks/useAutoScroll';
import styles from './ChatTranscript.module.css';
import type { PersistedMessage } from './types';
import type { ToolCallRecord } from './useChatStream';

export interface ChatTranscriptProps {
  messages: PersistedMessage[];
  isLoading: boolean;
  /** History load failure; distinct from a stream failure. */
  error: string | null;
  onRetry: () => void;
  isStreaming: boolean;
  intent: string | null;
  assistantText: string;
  toolCalls: ToolCallRecord[];
  streamError: string | null;
}

// The scrolling conversation surface: persisted rows, the in-flight stream,
// and the loading / empty / error states that replace them.
//
// It owns the scroll container (and therefore autoscroll) but no transport
// and no session state — every value it renders arrives as a prop, so it can
// be exercised without a network or a live stream.
export function ChatTranscript({
  messages,
  isLoading,
  error,
  onRetry,
  isStreaming,
  intent,
  assistantText,
  toolCalls,
  streamError,
}: ChatTranscriptProps) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  useAutoScroll(scrollerRef, [messages.length, assistantText, toolCalls.length]);

  const hasStreamOutput = Boolean(assistantText) || toolCalls.length > 0;
  const showEmptyState =
    !isLoading && !error && messages.length === 0 && !isStreaming && !hasStreamOutput;

  return (
    <div className={styles.scroller} ref={scrollerRef}>
      {isLoading && (
        <div className={styles.loadingState} role="status">
          <span className={styles.spinner} aria-hidden="true" />
          Loading conversation…
        </div>
      )}

      {error && (
        <div className={styles.historyError} role="alert">
          <span>{error}</span>
          <button type="button" className={styles.retryButton} onClick={onRetry}>
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

      {!isLoading &&
        !error &&
        messages.map((m) => <MessageRow key={m.id} message={m} />)}

      {isStreaming && (
        <div className={styles.streamingBlock}>
          {intent && <div className={styles.intent}>intent: {intent}</div>}
          {toolCalls.map((tc) => (
            <ToolCallChip key={tc.id} tool={tc} />
          ))}
          {assistantText && (
            <MessageBubble role="assistant" isStreaming>
              {assistantText}
            </MessageBubble>
          )}
        </div>
      )}

      {streamError && (
        <div className={styles.error} role="alert">
          <strong>error:</strong> {streamError}
        </div>
      )}
    </div>
  );
}
