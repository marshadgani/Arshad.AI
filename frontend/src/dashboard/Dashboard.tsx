import { AgentActivityCard } from './widgets/AgentActivityCard';
import { BriefingHero } from './widgets/BriefingHero';
import { DecisionQueueCard } from './widgets/DecisionQueueCard';
import { EventsCard } from './widgets/EventsCard';
import { FocusCard } from './widgets/FocusCard';
import { GitHubActivityCard } from './widgets/GitHubActivityCard';
import { HealthHabitsCard } from './widgets/HealthHabitsCard';
import { CommuteNewsCard } from './widgets/CommuteNewsCard';
import { KnowledgeSearchCard } from './widgets/KnowledgeSearchCard';
import { NotificationsCard } from './widgets/NotificationsCard';
import { QuickActionsCard } from './widgets/QuickActionsCard';
import { TasksCard } from './widgets/TasksCard';
import { WeatherCard } from './widgets/WeatherCard';
import { useDashboardData } from './useDashboardData';
import styles from './Dashboard.module.css';

// Composition only: transport lives in useDashboardData, each card's markup
// lives with the card. Row grouping is the responsive contract — every `row`
// collapses through the shared ladder in styles/grid.module.css, so cards
// placed in the same row are the cards that stack together on a phone.
export default function Dashboard() {
  const data = useDashboardData();

  return (
    <div className={styles.page}>
      <BriefingHero briefing={data.briefing} />

      <div className={`${styles.row} ${styles.cols2}`}>
        <FocusCard focus={data.focus} />
        <DecisionQueueCard
          decisions={data.decisions.data}
          isLoading={data.decisions.isLoading}
          error={data.decisions.error}
          mode={data.decisions.mode}
        />
      </div>

      <div className={`${styles.row} ${styles.cols3}`}>
        <TasksCard
          tasks={data.tasks.data}
          isLoading={data.tasks.isLoading}
          error={data.tasks.error}
          mode={data.tasks.mode}
        />
        <EventsCard events={data.events} />
        <AgentActivityCard
          agentActivity={data.agentActivity.data}
          isLoading={data.agentActivity.isLoading}
          error={data.agentActivity.error}
          mode={data.agentActivity.mode}
        />
      </div>

      <div className={styles.row}>
        <GitHubActivityCard
          items={data.githubActivity.data}
          isLoading={data.githubActivity.isLoading}
          error={data.githubActivity.error}
        />
      </div>

      <div className={`${styles.row} ${styles.cols3}`}>
        <HealthHabitsCard healthHabits={data.healthHabits} />
        <NotificationsCard
          notifications={data.notifications.data}
          isLoading={data.notifications.isLoading}
          error={data.notifications.error}
          mode={data.notifications.mode}
        />
        <div className={styles.stack}>
          <WeatherCard weather={data.weather} />
          <CommuteNewsCard commute={data.commute} news={data.news} />
        </div>
      </div>

      <div className={`${styles.row} ${styles.cols2}`}>
        <KnowledgeSearchCard suggestions={data.knowledgeSuggestions} />
        <QuickActionsCard quickActions={data.quickActions} />
      </div>
    </div>
  );
}
