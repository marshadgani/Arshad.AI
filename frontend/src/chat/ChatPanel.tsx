import { useEffect } from 'react';

import { ChatComposer } from './ChatComposer';
import { ChatTranscript } from './ChatTranscript';
import styles from './ChatPanel.module.css';
import { useChatHistory } from './useChatHistory';
import { useChatStream } from './useChatStream';

export interface ChatPanelProps {
  sessionId: string;
}

// Composition root for the chat surface: it joins persisted history
// (useChatHistory) to the live stream (useChatStream) and hands the result
// to presentational children. Transport lives in the hooks, message markup
// in ChatTranscript, draft state in ChatComposer — this file only wires
// them together and announces stream status.
export function ChatPanel({ sessionId }: ChatPanelProps) {
  const stream = useChatStream(sessionId);
  const history = useChatHistory(sessionId);

  const hasStreamOutput = Boolean(stream.assistantText) || stream.toolCalls.length > 0;

  let streamStatus = '';
  if (stream.isStreaming) streamStatus = 'Assistant is responding…';
  else if (stream.error) streamStatus = `Error: ${stream.error}`;

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

  return (
    <section className={styles.panel}>
      <div className="sr-only" aria-live="polite">
        {streamStatus}
      </div>

      <ChatTranscript
        messages={history.messages}
        isLoading={history.isLoading}
        error={history.error}
        onRetry={history.reload}
        isStreaming={stream.isStreaming}
        intent={stream.intent}
        assistantText={stream.assistantText}
        toolCalls={stream.toolCalls}
        streamError={stream.error}
      />

      <ChatComposer disabled={stream.isStreaming} onSubmit={handleSend} />
    </section>
  );
}
