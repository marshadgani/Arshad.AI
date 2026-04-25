import {
  type CalendarTag, type Severity,
  type Task, type Event, type Decision, type AgentTick,
  type Notification, type QuickAction,
} from '../data/mockData';
import { useFetch } from '../hooks/useFetch';
import styles from './Dashboard.module.css';

export interface DashboardProps {}

const calClass: Record<CalendarTag, string> = {
  work: styles.calWork, personal: styles.calPersonal, family: styles.calFamily, health: styles.calHealth,
};
const sevClass: Record<Severity, string> = {
  critical: styles.sevCritical, warn: styles.sevWarn, info: styles.sevInfo, ok: styles.sevOk,
};

// Server response shapes (only the fields this page consumes — full types live in mockData)
interface BriefingRes { greeting: string; date: string; summary: string; }
interface FocusRes { title: string; subtitle: string; context: string; action: string; }
interface WeatherRes { temp: string; condition: string; city: string; }
interface CommuteRes { eta: string; mode: string; dest: string; }
interface NewsRes { id: string; title: string; source: string; }
interface HabitRes { name: string; value: string; delta: string; }

export default function Dashboard(_: DashboardProps) {
  // Singletons
  const { data: briefing } = useFetch<BriefingRes>('/api/v1/dashboard/briefing');
  const { data: focus } = useFetch<FocusRes>('/api/v1/dashboard/focus');
  const { data: weather } = useFetch<WeatherRes>('/api/v1/dashboard/weather');
  const { data: commute } = useFetch<CommuteRes>('/api/v1/dashboard/commute');

  // Collections
  const { data: decisions } = useFetch<Decision[]>('/api/v1/dashboard/decisions');
  const { data: tasks } = useFetch<Task[]>('/api/v1/dashboard/tasks');
  const { data: events } = useFetch<Event[]>('/api/v1/dashboard/events');
  const { data: agentActivity } = useFetch<AgentTick[]>('/api/v1/dashboard/agent-activity');
  const { data: healthHabits } = useFetch<HabitRes[]>('/api/v1/dashboard/health-habits');
  const { data: notifications } = useFetch<Notification[]>('/api/v1/dashboard/notifications');
  const { data: news } = useFetch<NewsRes[]>('/api/v1/dashboard/news');
  const { data: knowledgeSuggestions } = useFetch<string[]>('/api/v1/dashboard/knowledge-suggestions');
  const { data: quickActions } = useFetch<QuickAction[]>('/api/v1/dashboard/quick-actions');

  return (
    <div className={styles.page}>
      {/* ── Daily Briefing ──────────────────────────────── */}
      <section className={styles.hero}>
        <div className={styles.heroLabel}>// SYSTEM BRIEFING — REAL-TIME</div>
        <h1 className={styles.heroGreeting}>{briefing?.greeting ?? 'Loading…'}</h1>
        <div className={styles.heroDate}>{briefing?.date ?? ''}</div>
        <p className={styles.heroSummary}>{briefing?.summary ?? ''}</p>
      </section>

      {/* ── Focus + Decision Queue ──────────────────────── */}
      <div className={`${styles.row} ${styles.cols2}`}>
        <section className={styles.focusBig}>
          <div className={styles.cardTitle}><span className={styles.dot} />Focus now</div>
          <h2 className={styles.focusTitle}>{focus?.title ?? '—'}</h2>
          <div className={styles.focusSubtitle}>{focus?.subtitle ?? ''}</div>
          <p className={styles.focusContext}>{focus?.context ?? ''}</p>
          <button className={styles.focusBtn}>{focus?.action ?? 'Open'}</button>
        </section>

        <section className={styles.card}>
          <div className={styles.cardHead}>
            <div className={styles.cardTitle}>Decision queue</div>
            <div className={styles.cardMeta}>{(decisions ?? []).length} waiting</div>
          </div>
          <div className={styles.list}>
            {(decisions ?? []).map((d) => (
              <div key={d.id} className={styles.decision}>
                <div className={styles.decisionTitle}>{d.title}</div>
                <div className={styles.decisionContext}>{d.context}</div>
                <div className={styles.decisionMeta}>
                  <span>{d.source}</span>
                  <span>waiting {d.waitingSince}</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* ── Tasks · Events · Agent ticker ───────────────── */}
      <div className={`${styles.row} ${styles.cols3}`}>
        <section className={styles.card}>
          <div className={styles.cardHead}>
            <div className={styles.cardTitle}>My tasks</div>
            <div className={styles.cardMeta}>{(tasks ?? []).length} open</div>
          </div>
          <div className={styles.list}>
            {(tasks ?? []).slice(0, 5).map((t) => (
              <div key={t.id} className={styles.row3}>
                <span className={`${styles.priority} ${styles[t.priority]}`}>{t.priority.toUpperCase()}</span>
                <span>
                  {t.title}<span className={styles.tag}>{t.source}</span>
                </span>
                <span
                  className={
                    `${styles.due} ` +
                    (t.due.startsWith('Yesterday') ? styles.dueOverdue :
                     t.due.startsWith('Today') ? styles.dueToday : '')
                  }
                >
                  {t.due}
                </span>
              </div>
            ))}
          </div>
        </section>

        <section className={styles.card}>
          <div className={styles.cardHead}>
            <div className={styles.cardTitle}>My events</div>
            <div className={styles.cardMeta}>today · 3 calendars</div>
          </div>
          <div className={styles.list}>
            {(events ?? []).map((e) => (
              <div key={e.id} className={styles.eventRow}>
                <div className={styles.eventTime}>{e.start}</div>
                <div className={`${styles.eventBar} ${calClass[e.calendar]}`} />
                <div>
                  <div className={styles.eventTitle}>{e.title}</div>
                  <div className={styles.eventMeta}>{e.calendar} · {e.source} · {e.duration}</div>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className={styles.card}>
          <div className={styles.cardHead}>
            <div className={styles.cardTitle}><span className={styles.dot} />Agent activity</div>
            <div className={styles.cardMeta}>live</div>
          </div>
          <div className={styles.list}>
            {(agentActivity ?? []).map((a) => (
              <div key={a.id} className={styles.tick}>
                <span className={styles.tickAgent}>{a.agent}</span>
                <span className={styles.tickMsg}>{a.message}</span>
                <span className={styles.tickTime}>{a.time}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* ── Health · Notifications · Weather/News ───────── */}
      <div className={`${styles.row} ${styles.cols3}`}>
        <section className={styles.card}>
          <div className={styles.cardHead}>
            <div className={styles.cardTitle}>Health & habits</div>
            <div className={styles.cardMeta}>last 24 h</div>
          </div>
          <div className={styles.healthGrid}>
            {(healthHabits ?? []).map((h) => (
              <div key={h.name} className={styles.healthCell}>
                <div className={styles.healthLabel}>{h.name}</div>
                <div className={styles.healthValue}>{h.value}</div>
                <div className={styles.healthDelta}>{h.delta}</div>
              </div>
            ))}
          </div>
        </section>

        <section className={styles.card}>
          <div className={styles.cardHead}>
            <div className={styles.cardTitle}>Notifications</div>
            <div className={styles.cardMeta}>{(notifications ?? []).length} new</div>
          </div>
          <div className={styles.list}>
            {(notifications ?? []).map((n) => (
              <div key={n.id} className={styles.notif}>
                <span className={`${styles.notifPin} ${sevClass[n.severity]}`} />
                <div className={styles.notifBody}>
                  <span className={styles.notifTitle}>{n.title}</span>
                  <span className={styles.notifDetail}>{n.detail}</span>
                </div>
                <span className={styles.notifTime}>{n.time}</span>
              </div>
            ))}
          </div>
        </section>

        <section className={styles.card}>
          <div className={styles.cardHead}>
            <div className={styles.cardTitle}>Weather · commute · news</div>
            <div className={styles.cardMeta}>{weather?.city ?? ''}</div>
          </div>
          <div className={styles.wxBig}>
            <div className={styles.wxTemp}>{weather?.temp ?? '—'}</div>
            <div className={styles.wxDetail}>{weather?.condition ?? ''}</div>
          </div>
          <div className={styles.wxRow}>
            <span className={styles.wxLabel}>Commute</span>
            <span className={styles.wxValue}>{commute ? `${commute.eta} · ${commute.dest}` : '—'}</span>
          </div>
          {(news ?? []).map((n) => (
            <div key={n.id} className={styles.wxRow}>
              <span className={styles.wxLabel}>{n.source}</span>
              <span className={styles.wxValue}>{n.title}</span>
            </div>
          ))}
        </section>
      </div>

      {/* ── Knowledge search · Quick actions ────────────── */}
      <div className={`${styles.row} ${styles.cols2}`}>
        <section className={styles.card}>
          <div className={styles.cardHead}>
            <div className={styles.cardTitle}>Knowledge search</div>
            <div className={styles.cardMeta}>docs · repos · notes · chats</div>
          </div>
          <div className={styles.searchBar}>
            <span style={{ color: 'var(--accent)' }}>⌕</span>
            <input
              className={styles.searchInput}
              placeholder='Search across all your knowledge — try "Q3 launch deck"'
            />
          </div>
          <div className={styles.searchSuggest}>
            {(knowledgeSuggestions ?? []).map((s) => (
              <button key={s} className={styles.suggestion}>{s}</button>
            ))}
          </div>
        </section>

        <section className={styles.card}>
          <div className={styles.cardHead}>
            <div className={styles.cardTitle}>Quick actions</div>
            <div className={styles.cardMeta}>shortcuts</div>
          </div>
          <div className={styles.qaGrid}>
            {(quickActions ?? []).map((q) => (
              <button key={q.id} className={styles.qa}>
                <div className={styles.qaLabel}>{q.label}</div>
                {q.hint && <div className={styles.qaHint}>{q.hint}</div>}
              </button>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
