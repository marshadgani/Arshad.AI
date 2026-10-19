import { FormEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { CHAT_PATH } from '../../routes/paths';
import { CardHeader } from '../CardHeader';
import styles from '../Dashboard.module.css';

export interface KnowledgeSearchCardProps {
  suggestions: string[] | null;
}

export function KnowledgeSearchCard({ suggestions }: KnowledgeSearchCardProps) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');

  // Searching hands the question to a new chat, prefilled, so you review it
  // and press Send. The chat assistant does the lookup with your tools.
  const ask = (text: string) => {
    const draft = text.trim();
    if (!draft) return;
    navigate(CHAT_PATH, { state: { draft } });
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    ask(query);
    setQuery('');
  };

  return (
    <section className={styles.card}>
      <CardHeader title="Knowledge search" meta="asks the chat assistant" />
      <form className={styles.searchBar} onSubmit={onSubmit} role="search">
        <span className={styles.searchIcon} aria-hidden="true">⌕</span>
        <input
          className={styles.searchInput}
          aria-label="Search your knowledge"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder='Search across all your knowledge — try "Q3 launch deck"'
        />
      </form>
      <div className={styles.searchSuggest}>
        {(suggestions ?? []).map((s) => (
          <button key={s} type="button" className={styles.suggestion} onClick={() => ask(s)}>
            {s}
          </button>
        ))}
      </div>
    </section>
  );
}
