import { useState } from 'react';
import { useFetch } from '../../hooks/useFetch';
import styles from './Obsidian.module.css';

interface NoteStats {
  total_notes: number;
  total_words: number;
  last_synced_at: string | null;
}

interface NoteSummary {
  id: string;
  title: string;
  path: string;
  excerpt: string;
  tags: string[];
  word_count: number;
  last_modified_at: string;
}

interface NoteFull extends NoteSummary {
  content: string;
  frontmatter: Record<string, unknown>;
  blob_sha: string;
}

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

function formatWords(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export default function Obsidian() {
  const [query, setQuery] = useState('');
  const [selectedNote, setSelectedNote] = useState<NoteFull | null>(null);
  const [syncing, setSyncing] = useState(false);

  const { data: statsData } = useFetch<{ data: NoteStats }>('/api/v1/obsidian/stats', 30_000);
  const stats = statsData?.data;

  const notesUrl = query.trim()
    ? `/api/v1/obsidian/notes?q=${encodeURIComponent(query)}&limit=50`
    : '/api/v1/obsidian/notes?limit=50';
  const { data: notesData } = useFetch<{ data: NoteSummary[]; total: number }>(notesUrl);
  const notes = notesData?.data ?? [];

  async function handleSync() {
    setSyncing(true);
    try {
      await fetch('/api/v1/obsidian/sync', { method: 'POST' });
    } finally {
      setTimeout(() => setSyncing(false), 2000);
    }
  }

  async function openNote(id: string) {
    const resp = await fetch(`/api/v1/obsidian/notes/${id}`);
    if (resp.ok) {
      const json = await resp.json();
      setSelectedNote(json.data as NoteFull);
    }
  }

  return (
    <div className={styles.page}>
      {/* Header */}
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Obsidian Vault</h1>
          <p className={styles.subtitle}>
            {stats
              ? `${stats.total_notes.toLocaleString()} notes · ${formatWords(stats.total_words)} words · synced ${formatDate(stats.last_synced_at)}`
              : 'Loading vault…'}
          </p>
        </div>
        <button
          type="button"
          className={`${styles.syncBtn} ${syncing ? styles.syncBtnActive : ''}`}
          onClick={handleSync}
          disabled={syncing}
        >
          {syncing ? 'Syncing…' : '↺ Sync Vault'}
        </button>
      </div>

      {/* Search */}
      <div className={styles.searchRow}>
        <input
          className={styles.searchInput}
          type="search"
          placeholder="Search notes…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {notesData && (
          <span className={styles.resultCount}>
            {notesData.total.toLocaleString()} note{notesData.total !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      <div className={styles.layout}>
        {/* Note list */}
        <div className={styles.list}>
          {notes.length === 0 ? (
            <div className={styles.empty}>
              {query ? 'No notes match your search.' : 'No notes yet — click Sync Vault to import your vault.'}
            </div>
          ) : (
            notes.map((note) => (
              <button
                key={note.id}
                type="button"
                className={`${styles.noteCard} ${selectedNote?.id === note.id ? styles.noteCardActive : ''}`}
                onClick={() => openNote(note.id)}
              >
                <div className={styles.noteTitle}>{note.title}</div>
                <div className={styles.notePath}>{note.path}</div>
                {note.excerpt && (
                  <div className={styles.noteExcerpt}>{note.excerpt}</div>
                )}
                <div className={styles.noteMeta}>
                  {note.tags.slice(0, 3).map((tag) => (
                    <span key={tag} className={styles.tag}>#{tag}</span>
                  ))}
                  <span className={styles.noteDate}>{formatDate(note.last_modified_at)}</span>
                  <span className={styles.noteWords}>{formatWords(note.word_count)}w</span>
                </div>
              </button>
            ))
          )}
        </div>

        {/* Note viewer */}
        {selectedNote && (
          <div className={styles.viewer}>
            <div className={styles.viewerHeader}>
              <div>
                <div className={styles.viewerTitle}>{selectedNote.title}</div>
                <div className={styles.viewerPath}>{selectedNote.path}</div>
              </div>
              <button
                type="button"
                className={styles.closeBtn}
                onClick={() => setSelectedNote(null)}
              >
                ×
              </button>
            </div>
            {selectedNote.tags.length > 0 && (
              <div className={styles.viewerTags}>
                {selectedNote.tags.map((t) => (
                  <span key={t} className={styles.tag}>#{t}</span>
                ))}
              </div>
            )}
            <pre className={styles.noteContent}>{selectedNote.content}</pre>
          </div>
        )}
      </div>
    </div>
  );
}
