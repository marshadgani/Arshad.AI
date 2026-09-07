import { useCallback, useEffect, useRef, useState } from 'react';

import { getToken } from '../auth/tokenStorage';

// SSE event shapes match backend services/chat.py. This is the ONE trust
// boundary for the stream: `JSON.parse` yields `unknown`, cast once to
// ChatSseEvent below, and every branch after that is a plain (checked)
// discriminated-union narrowing — no further per-field `as` casts.
// Terminator: data: [DONE]
export type ChatSseEvent =
  | { intent: string }
  | { delta: string }
  | { tool_use: { id: string; name: string; input: unknown } }
  | { tool_result: { id: string; name: string; output: unknown; is_error: boolean } }
  | { error: { code: string; message: string } };

// Discriminated on `status`: a call in flight never carries an `output` and
// a finished one always does, so the two states can no longer disagree the
// way independent optional fields could.
interface ToolCall { id: string; name: string; input: unknown }

export type ToolCallRecord =
  | (ToolCall & { status: 'running' })
  | (ToolCall & { status: 'completed' | 'error'; output: unknown });

export interface ChatStreamState {
  isStreaming: boolean;
  intent: string | null;
  assistantText: string;
  toolCalls: ToolCallRecord[];
  error: string | null;
}

const initialState: ChatStreamState = {
  isStreaming: false,
  intent: null,
  assistantText: '',
  toolCalls: [],
  error: null,
};

// Browsers' EventSource doesn't support custom headers (no Authorization),
// so we use fetch() and read the body stream by hand. The endpoint returns
// text/event-stream regardless.
export function useChatStream(sessionId: string | null) {
  const [state, setState] = useState<ChatStreamState>(initialState);
  const abortRef = useRef<AbortController | null>(null);

  // Aborts whatever stream is in flight whenever the caller switches to a
  // different session, and on unmount. Without this, a stream started for
  // session A keeps its reader loop running (and keeps calling setState)
  // after ChatPanel has moved on to session B or unmounted entirely — the
  // read is never cancelled by the browser on its own, so it leaks the
  // connection and bleeds session A's tokens into session B's view.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, [sessionId]);

  const send = useCallback(
    async (text: string): Promise<void> => {
      if (!sessionId) return;
      const token = getToken();
      if (!token) {
        setState((s) => ({ ...s, error: '401 Unauthorized' }));
        return;
      }

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setState({ ...initialState, isStreaming: true });

      let response: Response;
      try {
        response = await fetch(`/api/v1/chat/sessions/${sessionId}/messages`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
            Accept: 'text/event-stream',
          },
          body: JSON.stringify({ text }),
          signal: controller.signal,
        });
      } catch (err) {
        if ((err as Error).name === 'AbortError') return;
        setState((s) => ({ ...s, isStreaming: false, error: (err as Error).message }));
        return;
      }

      if (!response.ok || !response.body) {
        setState((s) => ({
          ...s,
          isStreaming: false,
          error: `${response.status} ${response.statusText}`,
        }));
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const events = buffer.split('\n\n');
          buffer = events.pop() ?? '';
          for (const raw of events) {
            const line = raw.trim();
            if (!line.startsWith('data:')) continue;
            const body = line.slice(5).trim();
            if (body === '[DONE]') {
              setState((s) => ({ ...s, isStreaming: false }));
              return;
            }
            let parsed: ChatSseEvent;
            try {
              parsed = JSON.parse(body) as ChatSseEvent;
            } catch {
              continue;
            }
            applyEvent(setState, parsed);
          }
        }
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          setState((s) => ({ ...s, isStreaming: false, error: (err as Error).message }));
        }
      } finally {
        setState((s) => ({ ...s, isStreaming: false }));
      }
    },
    [sessionId],
  );

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setState((s) => ({ ...s, isStreaming: false }));
  }, []);

  return { ...state, send, cancel };
}

function applyEvent(
  setState: React.Dispatch<React.SetStateAction<ChatStreamState>>,
  parsed: ChatSseEvent,
): void {
  if ('intent' in parsed) {
    setState((s) => ({ ...s, intent: parsed.intent }));
    return;
  }
  if ('delta' in parsed) {
    setState((s) => ({ ...s, assistantText: s.assistantText + parsed.delta }));
    return;
  }
  if ('tool_use' in parsed) {
    const tu = parsed.tool_use;
    setState((s) => ({
      ...s,
      toolCalls: [
        ...s.toolCalls,
        { id: tu.id, name: tu.name, input: tu.input, status: 'running' },
      ],
    }));
    return;
  }
  if ('tool_result' in parsed) {
    const tr = parsed.tool_result;
    setState((s) => ({
      ...s,
      toolCalls: s.toolCalls.map((c): ToolCallRecord =>
        c.id === tr.id
          ? { id: c.id, name: c.name, input: c.input, status: tr.is_error ? 'error' : 'completed', output: tr.output }
          : c,
      ),
    }));
    return;
  }
  if ('error' in parsed) {
    const err = parsed.error;
    setState((s) => ({ ...s, error: `${err.code}: ${err.message}`, isStreaming: false }));
  }
}
