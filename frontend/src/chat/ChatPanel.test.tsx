import { render, screen, waitFor } from '@testing-library/react';
import { vi } from 'vitest';

import { ChatPanel } from './ChatPanel';

const mockStream = {
  isStreaming: false,
  intent: null as string | null,
  assistantText: '',
  toolCalls: [] as Array<{ id: string; name: string; input: unknown; status: string }>,
  error: null as string | null,
  send: vi.fn(),
  cancel: vi.fn(),
};

vi.mock('./useChatStream', () => ({
  useChatStream: () => mockStream,
}));

function mockFetchOnce(response: { ok: boolean; status?: number; json?: () => unknown }) {
  return vi.fn().mockResolvedValue({
    ok: response.ok,
    status: response.status ?? 200,
    json: response.json ?? (() => Promise.resolve({ data: [] })),
  });
}

beforeEach(() => {
  mockStream.isStreaming = false;
  mockStream.assistantText = '';
  mockStream.toolCalls = [];
  mockStream.error = null;
});

describe('ChatPanel — four states', () => {
  it('shows a loading state while conversation history is being fetched', () => {
    global.fetch = vi.fn(() => new Promise(() => undefined)) as unknown as typeof fetch;
    render(<ChatPanel sessionId="s1" />);
    expect(screen.getByRole('status')).toHaveTextContent(/loading conversation/i);
  });

  it('shows an empty state when the conversation has no messages', async () => {
    global.fetch = mockFetchOnce({ ok: true, json: () => Promise.resolve({ data: [] }) });
    render(<ChatPanel sessionId="s1" />);
    await waitFor(() =>
      expect(screen.getByText(/ask arshad\.ai anything/i)).toBeInTheDocument(),
    );
  });

  it('shows an error state with a retry action when history fails to load', async () => {
    global.fetch = mockFetchOnce({ ok: false, status: 500 });
    render(<ChatPanel sessionId="s1" />);
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/could not load this conversation/i),
    );
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('shows content state with persisted messages rendered', async () => {
    global.fetch = mockFetchOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          data: [
            { id: '1', role: 'user', content: { text: 'Hi' }, created_at: null },
            { id: '2', role: 'assistant', content: { text: 'Hello there' }, created_at: null },
          ],
        }),
    });
    render(<ChatPanel sessionId="s1" />);
    await waitFor(() => expect(screen.getByText('Hello there')).toBeInTheDocument());
    expect(screen.getByText('Hi')).toBeInTheDocument();
    expect(screen.queryByText(/ask arshad\.ai anything/i)).not.toBeInTheDocument();
  });

  it('renders the composer with an accessible label', async () => {
    global.fetch = mockFetchOnce({ ok: true, json: () => Promise.resolve({ data: [] }) });
    render(<ChatPanel sessionId="s1" />);
    expect(await screen.findByLabelText(/message/i)).toBeInTheDocument();
  });
});
