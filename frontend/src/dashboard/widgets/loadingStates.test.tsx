import { render, screen } from '@testing-library/react';

import { type Decision, type Event, type Task } from '../../data/mockData';
import { DecisionQueueCard } from './DecisionQueueCard';
import { EventsCard } from './EventsCard';
import { TasksCard } from './TasksCard';

// Regression coverage for the live-browser-audit finding (FEAT-161): every
// dashboard widget takes `T[] | null`, where null means "still loading" and
// [] means "genuinely empty" — but every widget used to collapse both into
// the same "0 open"/"0 waiting" text with no visual distinction, so a slow
// network read looked identical to a broken/empty app for several seconds.
describe('dashboard widgets distinguish loading from empty', () => {
  it('DecisionQueueCard: null renders a loading state, not "0 waiting"', () => {
    render(<DecisionQueueCard decisions={null} />);
    expect(screen.queryByText('0 waiting')).not.toBeInTheDocument();
    expect(screen.getByText('···')).toBeInTheDocument();
  });

  it('DecisionQueueCard: [] renders an explicit empty message', () => {
    render(<DecisionQueueCard decisions={[]} />);
    expect(screen.getByText('0 waiting')).toBeInTheDocument();
    expect(screen.getByText('Nothing waiting on you right now.')).toBeInTheDocument();
  });

  it('DecisionQueueCard: populated data renders the real rows', () => {
    const decisions: Decision[] = [
      { id: 'd1', title: 'Approve X', context: 'ctx', source: 'github', waitingSince: '1 h' },
    ];
    render(<DecisionQueueCard decisions={decisions} />);
    expect(screen.getByText('1 waiting')).toBeInTheDocument();
    expect(screen.getByText('Approve X')).toBeInTheDocument();
    expect(screen.queryByText('Nothing waiting on you right now.')).not.toBeInTheDocument();
  });

  it('EventsCard: null does not render the "no events" empty copy (it is still loading)', () => {
    render(<EventsCard events={null} />);
    expect(screen.queryByText('No events today — your calendar is clear.')).not.toBeInTheDocument();
  });

  it('EventsCard: [] renders the confirmed-missing empty-state message', () => {
    render(<EventsCard events={[]} />);
    expect(screen.getByText('No events today — your calendar is clear.')).toBeInTheDocument();
  });

  it('EventsCard: populated data renders real event rows, not the empty message', () => {
    const events: Event[] = [
      { id: 'e1', title: 'Standup', start: '09:00', duration: '15m', calendar: 'work', source: 'Google' },
    ];
    render(<EventsCard events={events} />);
    expect(screen.getByText('Standup')).toBeInTheDocument();
    expect(screen.queryByText('No events today — your calendar is clear.')).not.toBeInTheDocument();
  });

  it('TasksCard: null renders a loading state, not "0 open"', () => {
    render(<TasksCard tasks={null} />);
    expect(screen.queryByText('0 open')).not.toBeInTheDocument();
    expect(screen.getByText('···')).toBeInTheDocument();
  });

  it('TasksCard: [] renders an explicit empty message', () => {
    render(<TasksCard tasks={[]} />);
    expect(screen.getByText('0 open')).toBeInTheDocument();
    expect(screen.getByText('No open tasks — inbox zero.')).toBeInTheDocument();
  });

  it('TasksCard: populated data renders the real rows', () => {
    const tasks: Task[] = [
      { id: 't1', title: 'Ship it', priority: 'p1', due: 'Today', source: 'github' },
    ];
    render(<TasksCard tasks={tasks} />);
    expect(screen.getByText('1 open')).toBeInTheDocument();
    expect(screen.getByText('Ship it')).toBeInTheDocument();
  });
});
