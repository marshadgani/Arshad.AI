import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';

import Chat from './Chat';

vi.mock('../chat/chatApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../chat/chatApi')>();
  return { ...actual, createChatSession: vi.fn().mockResolvedValue({ id: 'new-session' }) };
});

vi.mock('../chat/ChatPanel', () => ({
  ChatPanel: ({ sessionId, initialDraft }: { sessionId: string; initialDraft?: string }) => (
    <div data-testid="panel">
      {sessionId}|{initialDraft ?? ''}
    </div>
  ),
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
    renderChat({ pathname: '/chat', state: { draft: 'buy milk' } });
    expect(await screen.findByTestId('panel')).toHaveTextContent('new-session|buy milk');
  });

  it('opens a plain new chat with no draft when none was captured', async () => {
    renderChat('/chat');
    expect(await screen.findByTestId('panel')).toHaveTextContent('new-session|');
    expect(screen.getByTestId('panel')).not.toHaveTextContent('buy milk');
  });

  it('keeps showing an existing session as before', () => {
    renderChat('/chat/abc');
    expect(screen.getByTestId('panel')).toHaveTextContent('abc|');
  });
});
