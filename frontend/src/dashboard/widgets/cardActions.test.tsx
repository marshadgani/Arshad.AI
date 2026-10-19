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

describe('null and blank states', () => {
  it('shows no action buttons while quick actions load', () => {
    renderWithChat(<QuickActionsCard quickActions={null} />);
    expect(screen.queryAllByRole('button')).toHaveLength(0);
  });

  it('renders no suggestions while they load', () => {
    renderWithChat(<KnowledgeSearchCard suggestions={null} />);
    expect(screen.queryAllByRole('button')).toHaveLength(0);
  });

  it('matches the Open chat label by prefix and ignores case', async () => {
    renderWithChat(
      <QuickActionsCard
        quickActions={[
          { id: 'x', label: 'open chat' },
          { id: 'y', label: 'Reopen chat log' },
        ]}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Reopen chat log' }));
    expect(screen.getByTestId('chat')).toHaveTextContent('Reopen chat log');
  });

  it('opens an empty chat for a lowercase open chat label', async () => {
    renderWithChat(<QuickActionsCard quickActions={[{ id: 'x', label: 'open chat' }]} />);
    await userEvent.click(screen.getByRole('button', { name: 'open chat' }));
    expect(screen.getByTestId('chat')).toHaveTextContent('EMPTY');
  });

  it('tells the user when a blank query is submitted and keeps them on the dashboard', async () => {
    renderWithChat(<KnowledgeSearchCard suggestions={[]} />);
    await userEvent.type(screen.getByRole('textbox', { name: 'Search your knowledge' }), '   {Enter}');
    expect(screen.getByRole('alert')).toHaveTextContent('Type a question first');
    expect(screen.queryByTestId('chat')).toBeNull();
  });

  it('removes the blank hint once the user types again', async () => {
    renderWithChat(<KnowledgeSearchCard suggestions={[]} />);
    const input = screen.getByRole('textbox', { name: 'Search your knowledge' });
    await userEvent.type(input, '{Enter}');
    expect(screen.getByRole('alert')).toBeInTheDocument();
    await userEvent.type(input, 'a');
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('hands over the trimmed query exactly', async () => {
    function Exact() {
      const { state } = useLocation();
      return <div data-testid="exact">{JSON.stringify(state)}</div>;
    }
    render(
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<KnowledgeSearchCard suggestions={[]} />} />
          <Route path={CHAT_PATH} element={<Exact />} />
        </Routes>
      </MemoryRouter>,
    );
    await userEvent.type(screen.getByRole('textbox', { name: 'Search your knowledge' }), '  Q3 deck  {Enter}');
    expect(screen.getByTestId('exact').textContent).toBe('{"draft":"Q3 deck"}');
  });

  it('caps the typed query length', () => {
    renderWithChat(<KnowledgeSearchCard suggestions={[]} />);
    expect(screen.getByRole('textbox', { name: 'Search your knowledge' })).toHaveAttribute('maxlength', '500');
  });

  it('shows the agent skeleton when activity is still loading and rows when present', () => {
    const { rerender } = render(<AgentActivityCard agentActivity={null} />);
    expect(screen.getByText('recent runs')).toBeInTheDocument();
    rerender(
      <AgentActivityCard agentActivity={[{ id: '1', agent: 'inbox-bot', message: 'Sorted 4 threads', time: '2m' }]} />,
    );
    expect(screen.getByText('inbox-bot')).toBeInTheDocument();
    expect(screen.getByText('Sorted 4 threads')).toBeInTheDocument();
  });
});
