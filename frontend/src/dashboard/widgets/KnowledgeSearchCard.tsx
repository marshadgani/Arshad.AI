import { CardHeader } from '../CardHeader';
import styles from '../Dashboard.module.css';

export interface KnowledgeSearchCardProps {
  suggestions: string[] | null;
}

export function KnowledgeSearchCard({ suggestions }: KnowledgeSearchCardProps) {
  return (
    <section className={styles.card}>
      <CardHeader title="Knowledge search" meta="docs · repos · notes · chats" />
      <div className={styles.searchBar}>
        <span className={styles.searchIcon}>⌕</span>
        <input
          className={styles.searchInput}
          placeholder='Search across all your knowledge — try "Q3 launch deck"'
        />
      </div>
      <div className={styles.searchSuggest}>
        {(suggestions ?? []).map((s) => (
          <button key={s} className={styles.suggestion}>{s}</button>
        ))}
      </div>
    </section>
  );
}
