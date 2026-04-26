import { useCallback, useRef, useState } from 'react';

import { getToken } from '../auth/tokenStorage';

// SSE event shapes match backend services/chat.py:
//   {intent: "calendar"|"email"|"github"|"general"}
//   {delta: "<text chunk>"}
//   {tool_use: {id, name, input}}
//   {tool_result: {id, name, output, is_error}}
//   {error: {code, message}}
// Terminator: data: [DONE]

export type ChatEventType = 'intent' | 'delta' | 'tool_use' | 'tool_result' | 'error';

export interface ChatEvent {
  type: ChatEventType;
  payload: unknown;
}

export interface ToolCallRecord {
  id: string;
  name: string;
  input: unknown;
  output?: unknown;
  is_error?: boolean;
  status: 'running' | 'completed' | 'error';
}

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
            let parsed: Record<string, unknown>;
            try {
              parsed = JSON.parse(body);
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
  parsed: Record<string, unknown>,
): void {
  if ('intent' in parsed) {
    setState((s) => ({ ...s, intent: String(parsed.intent) }));
    return;
  }
  if ('delta' in parsed) {
    setState((s) => ({ ...s, assistantText: s.assistantText + String(parsed.delta) }));
    return;
  }
  if ('tool_use' in parsed) {
    const tu = parsed.tool_use as { id: string; name: string; input: unknown };
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
    const tr = parsed.tool_result as {
      id: string;
      name: string;
      output: unknown;
      is_error: boolean;
    };
    setState((s) => ({
      ...s,
      toolCalls: s.toolCalls.map((c) =>
        c.id === tr.id
          ? { ...c, output: tr.output, is_error: tr.is_error, status: tr.is_error ? 'error' : 'completed' }
          : c,
      ),
    }));
    return;
  }
  if ('error' in parsed) {
    const err = parsed.error as { code: string; message: string };
    setState((s) => ({ ...s, error: `${err.code}: ${err.message}`, isStreaming: false }));
  }
}
