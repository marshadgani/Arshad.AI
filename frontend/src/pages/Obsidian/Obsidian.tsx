import { useState } from 'react';
import { clearToken, getToken } from '../../auth/tokenStorage';
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
  const [syncError, setSyncError] = useState<string | null>(null);
  const [noteError, setNoteError] = useState<string | null>(null);

  const { data: stats } = useFetch<NoteStats>('/api/v1/obsidian/stats', 30_000);

  const notesUrl = query.trim()
    ? `/api/v1/obsidian/notes?q=${encodeURIComponent(query)}&limit=50`
    : '/api/v1/obsidian/notes?limit=50';
  const { data: notesData } = useFetch<{ notes: NoteSummary[]; total: number }>(notesUrl);
  const notes = notesData?.notes ?? [];

  function authHeaders(): Record<string, string> {
    const token = getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  function handle401() {
    clearToken();
    window.location.href = '/login';
  }

  async function handleSync() {
    setSyncing(true);
    setSyncError(null);
    try {
      const resp = await fetch('/api/v1/obsidian/sync', {
        method: 'POST',
        headers: authHeaders(),
      });
      if (resp.status === 401) { handle401(); return; }
      if (!resp.ok) setSyncError(`Sync failed (${resp.status})`);
    } catch {
      setSyncError('Sync failed: network error');
    } finally {
      setTimeout(() => setSyncing(false), 2000);
    }
  }

  async function openNote(id: string) {
    setNoteError(null);
    try {
      const resp = await fetch(`/api/v1/obsidian/notes/${id}`, { headers: authHeaders() });
      if (resp.status === 401) { handle401(); return; }
      if (resp.ok) {
        const json = await resp.json();
        setSelectedNote(json.data as NoteFull);
      } else {
        setNoteError('Could not load note.');
      }
    } catch {
      setNoteError('Could not load note: network error.');
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
        <div>
          <button
            type="button"
            className={`${styles.syncBtn} ${syncing ? styles.syncBtnActive : ''}`}
            onClick={handleSync}
            disabled={syncing}
          >
            {syncing ? 'Syncing…' : '↺ Sync Vault'}
          </button>
          {syncError && <p className={styles.syncError}>{syncError}</p>}
        </div>
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

      {noteError && <p className={styles.noteError}>{noteError}</p>}

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
