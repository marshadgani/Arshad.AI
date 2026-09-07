import {
  type AgentTick,
  type Decision,
  type Event,
  type Notification,
  type QuickAction,
  type Task,
} from '../data/mockData';
import { useFetch } from '../hooks/useFetch';

// Server response shapes for the endpoints only this page consumes. They
// declare the fields the dashboard actually reads, not the full row — the
// exhaustive domain types live in data/mockData.
export interface BriefingRes { greeting: string; date: string; summary: string }
export interface FocusRes { title: string; subtitle: string; context: string; action: string }
export interface WeatherRes { temp: string; condition: string; city: string }
export interface CommuteRes { eta: string; mode: string; dest: string }
export interface NewsRes { id: string; title: string; source: string }
export interface HabitRes { name: string; value: string; delta: string }

export interface DashboardData {
  briefing: BriefingRes | null;
  focus: FocusRes | null;
  weather: WeatherRes | null;
  commute: CommuteRes | null;
  decisions: Decision[] | null;
  tasks: Task[] | null;
  events: Event[] | null;
  agentActivity: AgentTick[] | null;
  healthHabits: HabitRes[] | null;
  notifications: Notification[] | null;
  news: NewsRes[] | null;
  knowledgeSuggestions: string[] | null;
  quickActions: QuickAction[] | null;
}

// Every dashboard read in one place, so widgets take data as props and can
// be rendered without a network layer.
//
// The thirteen requests stay independent on purpose — each card renders as
// soon as its own endpoint answers, so one slow widget never blocks the
// rest of the page. That is existing behaviour, preserved exactly.
export function useDashboardData(): DashboardData {
  return {
    briefing: useFetch<BriefingRes>('/api/v1/dashboard/briefing').data,
    focus: useFetch<FocusRes>('/api/v1/dashboard/focus').data,
    weather: useFetch<WeatherRes>('/api/v1/dashboard/weather').data,
    commute: useFetch<CommuteRes>('/api/v1/dashboard/commute').data,
    decisions: useFetch<Decision[]>('/api/v1/dashboard/decisions').data,
    tasks: useFetch<Task[]>('/api/v1/dashboard/tasks').data,
    events: useFetch<Event[]>('/api/v1/dashboard/events').data,
    agentActivity: useFetch<AgentTick[]>('/api/v1/dashboard/agent-activity').data,
    healthHabits: useFetch<HabitRes[]>('/api/v1/dashboard/health-habits').data,
    notifications: useFetch<Notification[]>('/api/v1/dashboard/notifications').data,
    news: useFetch<NewsRes[]>('/api/v1/dashboard/news').data,
    knowledgeSuggestions: useFetch<string[]>('/api/v1/dashboard/knowledge-suggestions').data,
    quickActions: useFetch<QuickAction[]>('/api/v1/dashboard/quick-actions').data,
  };
}
