import {
  type AgentTick,
  type Decision,
  type Event,
  type Notification,
  type QuickAction,
  type Task,
} from '../data/mockData';
import { useFetch } from '../hooks/useFetch';

// Full request state for the four widgets that render distinct
// loading/empty/error/content states and — for the three backed by live
// ingestion (tasks, agent activity, notifications) — a live-vs-seed badge.
// Everything else on this page keeps the plain `T | null` shape below;
// only these cards needed the extra fields, so only they pay for it.
export interface WidgetState<T> {
  data: T | null;
  isLoading: boolean;
  error: Error | null;
  mode?: string;
  /**
   * Re-run the request now — used by the cards that offer a retry action
   * (e.g. WeatherCard's degraded/error states). Optional so a card can be
   * rendered in a test without wiring one up.
   */
  refetch?: () => void;
}

// Server response shapes for the endpoints only this page consumes. They
// declare the fields the dashboard actually reads, not the full row — the
// exhaustive domain types live in data/mockData.
export interface BriefingRes { greeting: string; date: string; summary: string }
export interface FocusRes { title: string; subtitle: string; context: string; action: string }
export interface WeatherRes {
  temp: string | null;
  condition: string | null;
  city: string | null;
  connected: boolean;
  needs_reauth: boolean;
  degraded: boolean;
}
export interface CommuteRes { eta: string; mode: string; dest: string }
export interface NewsRes { id: string; title: string; source: string }
export interface HabitRes { name: string; value: string; delta: string }
export interface GitHubActivityRes {
  id: string;
  title: string;
  url: string | null;
  number: number | null;
  repository: string;
  kind: 'issue' | 'pr';
  state: 'open' | 'closed' | 'merged';
  isDraft: boolean;
  author: string | null;
  updatedAt: string;
}

export interface DashboardData {
  briefing: BriefingRes | null;
  focus: FocusRes | null;
  weather: WidgetState<WeatherRes>;
  commute: CommuteRes | null;
  decisions: WidgetState<Decision[]>;
  tasks: WidgetState<Task[]>;
  events: Event[] | null;
  agentActivity: WidgetState<AgentTick[]>;
  healthHabits: HabitRes[] | null;
  notifications: WidgetState<Notification[]>;
  news: NewsRes[] | null;
  knowledgeSuggestions: string[] | null;
  quickActions: QuickAction[] | null;
  githubActivity: WidgetState<GitHubActivityRes[]>;
}

// Every dashboard read in one place, so widgets take data as props and can
// be rendered without a network layer.
//
// The fourteen requests stay independent on purpose — each card renders as
// soon as its own endpoint answers, so one slow widget never blocks the
// rest of the page. That is existing behaviour, preserved exactly.
export function useDashboardData(): DashboardData {
  const decisions = useFetch<Decision[]>('/api/v1/dashboard/decisions');
  const tasks = useFetch<Task[]>('/api/v1/dashboard/tasks');
  const agentActivity = useFetch<AgentTick[]>('/api/v1/dashboard/agent-activity');
  const notifications = useFetch<Notification[]>('/api/v1/dashboard/notifications');
  const weather = useFetch<WeatherRes>('/api/v1/dashboard/weather');
  const githubActivity = useFetch<GitHubActivityRes[]>('/api/v1/dashboard/github-activity');

  // UseFetchResult is already a WidgetState — the widget cards read the
  // fields they need and ignore the rest, so these pass through whole.
  return {
    briefing: useFetch<BriefingRes>('/api/v1/dashboard/briefing').data,
    focus: useFetch<FocusRes>('/api/v1/dashboard/focus').data,
    weather,
    commute: useFetch<CommuteRes>('/api/v1/dashboard/commute').data,
    decisions,
    tasks,
    events: useFetch<Event[]>('/api/v1/dashboard/events').data,
    agentActivity,
    healthHabits: useFetch<HabitRes[]>('/api/v1/dashboard/health-habits').data,
    notifications,
    news: useFetch<NewsRes[]>('/api/v1/dashboard/news').data,
    knowledgeSuggestions: useFetch<string[]>('/api/v1/dashboard/knowledge-suggestions').data,
    quickActions: useFetch<QuickAction[]>('/api/v1/dashboard/quick-actions').data,
    githubActivity,
  };
}
