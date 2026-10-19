import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { CHAT_PATH } from '../../routes/paths';
import { AgentActivityCard } from './AgentActivityCard';
import { KnowledgeSearchCard } from './KnowledgeSearchCard';
import { QuickActionsCard } from './QuickActionsCard';

function Landing() {
  const { state } = useLocation();
  return <div data-testid="chat">{(state as { draft?: string } | null)?.draft ?? 'EMPTY'}</div>;
}

function renderWithChat(ui: JSX.Element) {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={ui} />
        <Route path={CHAT_PATH} element={<Landing />} />
      </Routes>
    </MemoryRouter>,
  );
}

const actions = [
  { id: 'a', label: 'Add task', hint: 'tasks' },
  { id: 'b', label: 'Open chatbot', hint: 'chat' },
];

describe('QuickActionsCard', () => {
  it('opens a chat with the action prefilled', async () => {
    renderWithChat(<QuickActionsCard quickActions={actions} />);
    await userEvent.click(screen.getByRole('button', { name: /Add task/ }));
    expect(screen.getByTestId('chat')).toHaveTextContent('Add task');
  });

  it('opens an empty chat for Open chatbot', async () => {
    renderWithChat(<QuickActionsCard quickActions={actions} />);
    await userEvent.click(screen.getByRole('button', { name: /Open chatbot/ }));
    expect(screen.getByTestId('chat')).toHaveTextContent('EMPTY');
  });
});

describe('KnowledgeSearchCard', () => {
  it('opens a chat with the typed query on submit', async () => {
    renderWithChat(<KnowledgeSearchCard suggestions={[]} />);
    await userEvent.type(screen.getByRole('textbox', { name: 'Search your knowledge' }), 'Q3 deck{Enter}');
    expect(screen.getByTestId('chat')).toHaveTextContent('Q3 deck');
  });

  it('ignores an empty or blank query', async () => {
    renderWithChat(<KnowledgeSearchCard suggestions={[]} />);
    await userEvent.type(screen.getByRole('textbox', { name: 'Search your knowledge' }), '   {Enter}');
    expect(screen.queryByTestId('chat')).toBeNull();
  });

  it('opens a chat with the clicked suggestion', async () => {
    renderWithChat(<KnowledgeSearchCard suggestions={['Roadmap notes']} />);
    await userEvent.click(screen.getByRole('button', { name: 'Roadmap notes' }));
    expect(screen.getByTestId('chat')).toHaveTextContent('Roadmap notes');
  });
});

describe('AgentActivityCard', () => {
  it('does not claim to be live', () => {
    render(<AgentActivityCard agentActivity={[]} />);
    expect(screen.queryByText('live')).toBeNull();
    expect(screen.getByText('recent runs')).toBeInTheDocument();
  });
});
