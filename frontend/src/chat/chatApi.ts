import { getToken } from '../auth/tokenStorage';
import type { PersistedMessage } from './types';

// All non-streaming chat HTTP lives here. Components and hooks state *what*
// they need; this module owns the URLs, the auth header, and the
// `{ data: ... }` envelope defined in .claude/rules/api.md. Streaming is
// separate — see useChatStream.ts, which must read the response body by hand.

export class MissingTokenError extends Error {
  constructor() {
    super('No auth token available.');
    this.name = 'MissingTokenError';
  }
}

function authHeaders(): Record<string, string> {
  return { Authorization: `Bearer ${getToken() ?? ''}` };
}

async function unwrap<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(`${response.status}`);
  const body = await response.json();
  return body.data as T;
}

export async function fetchChatMessages(sessionId: string): Promise<PersistedMessage[]> {
  const response = await fetch(`/api/v1/chat/sessions/${sessionId}/messages`, {
    headers: authHeaders(),
  });
  return (await unwrap<PersistedMessage[] | null>(response)) ?? [];
}

export interface ChatSession {
  id: string;
}

// Throws MissingTokenError rather than firing a request that is certain to
// 401, so callers can show a "sign in again" message instead of a generic
// failure.
export async function createChatSession(): Promise<ChatSession> {
  if (!getToken()) throw new MissingTokenError();
  const response = await fetch('/api/v1/chat/sessions', {
    method: 'POST',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });
  return unwrap<ChatSession>(response);
}
