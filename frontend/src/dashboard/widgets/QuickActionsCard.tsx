import { useNavigate } from 'react-router-dom';

import { type QuickAction } from '../../data/mockData';
import { CHAT_PATH } from '../../routes/paths';
import { CardHeader } from '../CardHeader';
import styles from '../Dashboard.module.css';

export interface QuickActionsCardProps {
  quickActions: QuickAction[] | null;
}

const OPEN_CHAT_LABEL = /^open chat/i;

export function QuickActionsCard({ quickActions }: QuickActionsCardProps) {
  const navigate = useNavigate();

  // An action opens a new chat with its label prefilled so you review it and
  // press Send. "Open chatbot" opens an empty chat. Nothing is sent on click.
  const run = (q: QuickAction) =>
    navigate(CHAT_PATH, OPEN_CHAT_LABEL.test(q.label) ? undefined : { state: { draft: q.label } });

  return (
    <section className={styles.card}>
      <CardHeader title="Quick actions" meta="shortcuts" />
      <div className={styles.qaGrid}>
        {(quickActions ?? []).map((q) => (
          <button key={q.id} type="button" className={styles.qa} onClick={() => run(q)}>
            <div className={styles.qaLabel}>{q.label}</div>
            {q.hint && <div className={styles.qaHint}>{q.hint}</div>}
          </button>
        ))}
      </div>
    </section>
  );
}
