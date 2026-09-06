import { useCallback, useEffect, useState } from 'react';

import { fetchChatMessages } from './chatApi';
import type { PersistedMessage } from './types';

export interface ChatHistory {
  messages: PersistedMessage[];
  isLoading: boolean;
  error: string | null;
  /** Re-load with visible loading and error states — for user-driven retry. */
  reload: () => void;
  /** Re-load silently; used to replace optimistic rows with canonical ones. */
  refresh: () => void;
  appendOptimistic: (text: string) => void;
}

// Owns everything about persisted conversation state: loading it, its four
// UI states, and optimistic insertion. ChatPanel renders it and no longer
// speaks HTTP.
export function useChatHistory(sessionId: string): ChatHistory {
  const [messages, setMessages] = useState<PersistedMessage[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let active = true;
    setIsLoading(true);
    setError(null);
    fetchChatMessages(sessionId)
      .then((data) => {
        if (active) setMessages(data);
      })
      .catch(() => {
        if (!active) return;
        setMessages([]);
        setError('Could not load this conversation.');
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [sessionId, reloadToken]);

  const reload = useCallback(() => setReloadToken((t) => t + 1), []);

  const refresh = useCallback(() => {
    // Deliberately silent: this runs after a successful stream, where the
    // user already has the assistant's reply on screen. A failed refresh
    // leaves the optimistic view intact rather than flashing an error.
    fetchChatMessages(sessionId)
      .then(setMessages)
      .catch(() => undefined);
  }, [sessionId]);

  const appendOptimistic = useCallback((text: string) => {
    setMessages((current) => [
      ...current,
      { id: `optimistic-${Date.now()}`, role: 'user', content: { text }, created_at: null },
    ]);
  }, []);

  return { messages, isLoading, error, reload, refresh, appendOptimistic };
}
