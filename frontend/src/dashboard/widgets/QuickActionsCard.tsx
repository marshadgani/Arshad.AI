import { useHandOffToChat } from '../../hooks/useHandOffToChat';
import { type QuickAction } from '../../data/mockData';
import { CardHeader } from '../CardHeader';
import { CardSkeleton } from '../CardSkeleton';
import styles from '../Dashboard.module.css';

export interface QuickActionsCardProps {
  quickActions: QuickAction[] | null;
}

// Actions come from the database with no action type, so the one that should
// open an empty chat ("Open chatbot") is recognised by its label prefix. Any
// other label is a prompt that opens prefilled.
const OPEN_CHAT_LABEL = /^open chat/i;

export function QuickActionsCard({ quickActions }: QuickActionsCardProps) {
  const { handOff, openEmpty } = useHandOffToChat();

  const run = (q: QuickAction) => {
    if (OPEN_CHAT_LABEL.test(q.label)) openEmpty();
    else handOff(q.label);
  };

  return (
    <section className={styles.card}>
      <CardHeader title="Quick actions" meta="shortcuts" />
      {quickActions === null ? (
        <CardSkeleton />
      ) : (
        <div className={styles.qaGrid}>
          {quickActions.map((q) => (
            <button key={q.id} type="button" className={styles.qa} onClick={() => run(q)}>
              <div className={styles.qaLabel}>{q.label}</div>
              {q.hint && <div className={styles.qaHint}>{q.hint}</div>}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
