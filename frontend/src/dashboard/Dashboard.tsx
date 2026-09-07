import { AgentActivityCard } from './widgets/AgentActivityCard';
import { BriefingHero } from './widgets/BriefingHero';
import { DecisionQueueCard } from './widgets/DecisionQueueCard';
import { EventsCard } from './widgets/EventsCard';
import { FocusCard } from './widgets/FocusCard';
import { HealthHabitsCard } from './widgets/HealthHabitsCard';
import { KnowledgeSearchCard } from './widgets/KnowledgeSearchCard';
import { NotificationsCard } from './widgets/NotificationsCard';
import { QuickActionsCard } from './widgets/QuickActionsCard';
import { TasksCard } from './widgets/TasksCard';
import { WeatherCommuteNewsCard } from './widgets/WeatherCommuteNewsCard';
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
        <DecisionQueueCard decisions={data.decisions} />
      </div>

      <div className={`${styles.row} ${styles.cols3}`}>
        <TasksCard tasks={data.tasks} />
        <EventsCard events={data.events} />
        <AgentActivityCard agentActivity={data.agentActivity} />
      </div>

      <div className={`${styles.row} ${styles.cols3}`}>
        <HealthHabitsCard healthHabits={data.healthHabits} />
        <NotificationsCard notifications={data.notifications} />
        <WeatherCommuteNewsCard
          weather={data.weather}
          commute={data.commute}
          news={data.news}
        />
      </div>

      <div className={`${styles.row} ${styles.cols2}`}>
        <KnowledgeSearchCard suggestions={data.knowledgeSuggestions} />
        <QuickActionsCard quickActions={data.quickActions} />
      </div>
    </div>
  );
}
