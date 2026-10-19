import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { vi } from 'vitest';

import Chat from './Chat';

vi.mock('../chat/chatApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../chat/chatApi')>();
  return { ...actual, createChatSession: vi.fn().mockResolvedValue({ id: 'new-session' }) };
});

const panelProps: Array<{ sessionId: string; initialDraft?: string }> = [];

vi.mock('../chat/ChatPanel', () => ({
  ChatPanel: (props: { sessionId: string; initialDraft?: string }) => {
    panelProps.push(props);
    return <div data-testid="panel">{props.sessionId}</div>;
  },
}));

function renderChat(entry: string | { pathname: string; state?: unknown }) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/chat" element={<Chat />} />
        <Route path="/chat/:sessionId" element={<Chat />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('Chat page quick-capture draft', () => {
  it('carries a quick-capture draft through the new-session redirect into the composer', async () => {
    panelProps.length = 0;
    renderChat({ pathname: '/chat', state: { draft: 'buy milk' } });
    expect(await screen.findByTestId('panel')).toHaveTextContent('new-session');
    expect(panelProps[0]).toEqual({ sessionId: 'new-session', initialDraft: 'buy milk' });
  });

  it('opens a plain new chat with no draft when none was captured', async () => {
    panelProps.length = 0;
    renderChat('/chat');
    expect(await screen.findByTestId('panel')).toHaveTextContent('new-session');
    expect(panelProps[0].initialDraft).toBeUndefined();
  });

  it('keeps showing an existing session as before', () => {
    renderChat('/chat/abc');
    expect(screen.getByTestId('panel')).toHaveTextContent('abc');
  });

  it('clears the draft from history once the panel has it, so a reload does not refill it', async () => {
    panelProps.length = 0;
    renderChat({ pathname: '/chat', state: { draft: 'sent already' } });
    await screen.findByTestId('panel');
    await waitFor(() => expect(panelProps[panelProps.length - 1]?.initialDraft).toBeUndefined());
    expect(panelProps[0].initialDraft).toBe('sent already');
  });
});

describe('Chat page failure and cleanup paths', () => {
  it('keeps and shows the captured text when the session cannot be created', async () => {
    const api = await import('../chat/chatApi');
    vi.mocked(api.createChatSession).mockRejectedValueOnce(new Error('network'));
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    renderChat({ pathname: '/chat', state: { draft: 'buy milk' } });
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not start/i);
    expect(screen.getByText(/your text is kept/i)).toHaveTextContent('buy milk');
    expect(consoleError).toHaveBeenCalled();
    consoleError.mockRestore();
  });

  it('creates exactly one session for one quick capture', async () => {
    const api = await import('../chat/chatApi');
    vi.mocked(api.createChatSession).mockClear();
    renderChat({ pathname: '/chat', state: { draft: 'once' } });
    await screen.findByTestId('panel');
    expect(api.createChatSession).toHaveBeenCalledTimes(1);
  });
});

describe('Chat page reuse and hardening', () => {
  it('starts a fresh session when a capture arrives while a chat is open', async () => {
    const api = await import('../chat/chatApi');
    vi.mocked(api.createChatSession).mockClear();
    vi.mocked(api.createChatSession).mockResolvedValueOnce({ id: 'fresh' } as never);
    panelProps.length = 0;
    function Capture() {
      const navigate = useNavigate();
      return (
        <button type="button" onClick={() => navigate('/chat', { state: { draft: 'later' } })}>
          capture
        </button>
      );
    }
    render(
      <MemoryRouter initialEntries={['/chat/abc']}>
        <Capture />
        <Routes>
          <Route path="/chat" element={<Chat />} />
          <Route path="/chat/:sessionId" element={<Chat />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByTestId('panel')).toHaveTextContent('abc');
    screen.getByRole('button', { name: 'capture' }).click();
    await waitFor(() => expect(screen.getByTestId('panel')).toHaveTextContent('fresh'));
    expect(api.createChatSession).toHaveBeenCalledTimes(1);
    expect(panelProps.some((p) => p.initialDraft === 'later')).toBe(true);
  });

  it('ignores a draft that is not a string', async () => {
    panelProps.length = 0;
    renderChat({ pathname: '/chat', state: { draft: { evil: true } } });
    await screen.findByTestId('panel');
    expect(panelProps[0].initialDraft).toBeUndefined();
  });

  it('retries with the kept text after a failed start', async () => {
    const api = await import('../chat/chatApi');
    vi.mocked(api.createChatSession).mockRejectedValueOnce(new Error('network'));
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    panelProps.length = 0;
    renderChat({ pathname: '/chat', state: { draft: 'keep me' } });
    await screen.findByRole('alert');
    screen.getByRole('button', { name: /try again/i }).click();
    await screen.findByTestId('panel');
    expect(panelProps[0].initialDraft).toBe('keep me');
    consoleError.mockRestore();
  });
});
