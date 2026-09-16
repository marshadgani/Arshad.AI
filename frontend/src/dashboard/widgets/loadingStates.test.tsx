import { render, screen } from '@testing-library/react';

import { type AgentTick, type Decision, type Event, type Notification, type Task } from '../../data/mockData';
import { AgentActivityCard } from './AgentActivityCard';
import { BriefingHero } from './BriefingHero';
import { DecisionQueueCard } from './DecisionQueueCard';
import { EventsCard } from './EventsCard';
import { FocusCard } from './FocusCard';
import { HealthHabitsCard } from './HealthHabitsCard';
import { NotificationsCard } from './NotificationsCard';
import { TasksCard } from './TasksCard';
import { WeatherCommuteNewsCard } from './WeatherCommuteNewsCard';

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

  it('NotificationsCard: null renders a loading state, not "0 new"', () => {
    render(<NotificationsCard notifications={null} />);
    expect(screen.queryByText('0 new')).not.toBeInTheDocument();
    expect(screen.getByText('···')).toBeInTheDocument();
  });

  it('NotificationsCard: [] renders an explicit empty message', () => {
    render(<NotificationsCard notifications={[]} />);
    expect(screen.getByText('No new notifications.')).toBeInTheDocument();
  });

  it('NotificationsCard: populated data renders the real rows', () => {
    const notifications: Notification[] = [
      { id: 'n1', severity: 'warn', title: 'Bill due', detail: 'detail', time: '12:00' },
    ];
    render(<NotificationsCard notifications={notifications} />);
    expect(screen.getByText('1 new')).toBeInTheDocument();
    expect(screen.getByText('Bill due')).toBeInTheDocument();
  });

  it('HealthHabitsCard: null renders a loading state, not the empty message', () => {
    render(<HealthHabitsCard healthHabits={null} />);
    expect(screen.queryByText('Connect Whoop or Apple Health to see habits here.')).not.toBeInTheDocument();
  });

  it('HealthHabitsCard: [] renders an explicit empty message', () => {
    render(<HealthHabitsCard healthHabits={[]} />);
    expect(screen.getByText('Connect Whoop or Apple Health to see habits here.')).toBeInTheDocument();
  });

  it('HealthHabitsCard: populated data renders the real cells', () => {
    render(<HealthHabitsCard healthHabits={[{ name: 'Sleep', value: '7h', delta: '+10m' }]} />);
    expect(screen.getByText('Sleep')).toBeInTheDocument();
    expect(screen.queryByText('Connect Whoop or Apple Health to see habits here.')).not.toBeInTheDocument();
  });

  it('AgentActivityCard: null renders a loading state, not the empty message', () => {
    render(<AgentActivityCard agentActivity={null} />);
    expect(screen.queryByText('No agent activity yet.')).not.toBeInTheDocument();
  });

  it('AgentActivityCard: [] renders an explicit empty message', () => {
    render(<AgentActivityCard agentActivity={[]} />);
    expect(screen.getByText('No agent activity yet.')).toBeInTheDocument();
  });

  it('AgentActivityCard: populated data renders the real rows', () => {
    const ticks: AgentTick[] = [{ id: 't1', agent: 'chat-orchestrator', message: 'Routed query', time: '14:25' }];
    render(<AgentActivityCard agentActivity={ticks} />);
    expect(screen.getByText('Routed query')).toBeInTheDocument();
  });

  it('BriefingHero: null renders a skeleton, not the greeting text', () => {
    render(<BriefingHero briefing={null} />);
    expect(screen.queryByText('Good evening, Arshad')).not.toBeInTheDocument();
  });

  it('BriefingHero: populated data renders the real greeting', () => {
    render(
      <BriefingHero briefing={{ greeting: 'Good evening, Arshad', date: 'Monday', summary: 'summary' }} />,
    );
    expect(screen.getByText('Good evening, Arshad')).toBeInTheDocument();
  });

  it('FocusCard: null renders a skeleton, not a placeholder title', () => {
    render(<FocusCard focus={null} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('FocusCard: populated data renders the real title and action', () => {
    render(
      <FocusCard
        focus={{ title: 'Reply to Sarah', subtitle: 'sub', context: 'ctx', action: 'Open in Gmail' }}
      />,
    );
    expect(screen.getByText('Reply to Sarah')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open in Gmail' })).toBeInTheDocument();
  });

  it('WeatherCommuteNewsCard: null props render skeletons/placeholders, not real values', () => {
    render(<WeatherCommuteNewsCard weather={null} commute={null} news={null} />);
    expect(screen.getByText('···')).toBeInTheDocument();
  });

  it('WeatherCommuteNewsCard: [] news renders an explicit empty message', () => {
    render(<WeatherCommuteNewsCard weather={null} commute={null} news={[]} />);
    expect(screen.getByText('No headlines right now.')).toBeInTheDocument();
  });

  it('WeatherCommuteNewsCard: populated data renders real weather/commute/news', () => {
    render(
      <WeatherCommuteNewsCard
        weather={{ temp: '28°C', condition: 'Cloudy', city: 'Bengaluru' }}
        commute={{ eta: '24 min', mode: 'car', dest: 'Office' }}
        news={[{ id: 'n1', title: 'GDP grew', source: 'Reuters' }]}
      />,
    );
    expect(screen.getByText('28°C')).toBeInTheDocument();
    expect(screen.getByText('24 min · Office')).toBeInTheDocument();
    expect(screen.getByText('GDP grew')).toBeInTheDocument();
  });
});
