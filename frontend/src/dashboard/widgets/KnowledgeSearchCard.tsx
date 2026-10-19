import { FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';

import { MAX_HANDOFF_CHARS, useHandOffToChat } from '../../hooks/useHandOffToChat';
import { CardHeader } from '../CardHeader';
import { CardSkeleton } from '../CardSkeleton';
import styles from '../Dashboard.module.css';

export interface KnowledgeSearchCardProps {
  suggestions: string[] | null;
}

export function KnowledgeSearchCard({ suggestions }: KnowledgeSearchCardProps) {
  const { handOff } = useHandOffToChat();
  const [query, setQuery] = useState('');
  const [blank, setBlank] = useState(false);

  // Searching hands the question to a new chat, prefilled, so you review it
  // and press Send. The chat assistant does the lookup with your tools.
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (handOff(query)) setQuery('');
    else setBlank(true);
  };

  return (
    <section className={styles.card}>
      <CardHeader title="Knowledge search" meta="asks the chat assistant" />
      <form className={styles.searchBar} onSubmit={onSubmit} role="search">
        <span className={styles.searchIcon} aria-hidden="true">⌕</span>
        <input
          className={styles.searchInput}
          aria-label="Search your knowledge"
          aria-invalid={blank}
          maxLength={MAX_HANDOFF_CHARS}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setBlank(false);
          }}
          placeholder='Search across all your knowledge — try "Q3 launch deck"'
        />
      </form>
      {blank && <p role="alert">Type a question first, then press Enter.</p>}
      {suggestions === null ? (
        <CardSkeleton rows={1} />
      ) : (
        <div className={styles.searchSuggest}>
          {suggestions.length === 0 && (
            <p>
              No suggestions yet. Connect or sync Google Drive on the{' '}
              <Link to="/integrations">Integrations page</Link> to see your recent files here.
            </p>
          )}
          {suggestions.map((s) => (
            <button key={s} type="button" className={styles.suggestion} onClick={() => handOff(s)}>
              {s}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
