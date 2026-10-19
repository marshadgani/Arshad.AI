import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { useCallback, useEffect, useRef, useState } from 'react';

import { ChatPanel } from '../chat/ChatPanel';
import { CHAT_PATH } from '../routes/paths';
import { MissingTokenError, createChatSession } from '../chat/chatApi';
import styles from './Chat.module.css';

export default function Chat() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const stateDraft = (location.state as { draft?: unknown } | null)?.draft;
  const draft = typeof stateDraft === 'string' ? stateDraft : undefined;
  const [error, setError] = useState<string | null>(null);
  // After a failed start the text moves out of browser history (so Back does
  // not show it to the next person) and is kept here instead.
  const [keptDraft, setKeptDraft] = useState<string | undefined>(undefined);
  // The redirect must carry the newest captured text, but a changing draft
  // must never create a second session, so read it through a ref.
  const draftRef = useRef(draft);
  // Keep the newest captured text even after it is cleared from history, so a
  // retry after a failed start still carries it.
  if (draft !== undefined) draftRef.current = draft;
  const startedRef = useRef(false);

  const startSession = useCallback(() => {
    setError(null);
    createChatSession()
      .then((session) =>
        navigate(`${CHAT_PATH}/${session.id}`, {
          replace: true,
          state: draftRef.current ? { draft: draftRef.current } : undefined,
        }),
      )
      .catch((err) => {
        console.error('Could not create a chat session', err);
        setKeptDraft(draftRef.current);
        setError(
          err instanceof MissingTokenError
            ? 'You need to sign in again before starting a chat.'
            : 'Could not start a new chat session.',
        );
      });
  }, [navigate]);

  // Once a session is open the captured text has been handed over; forget it so
  // a later plain /chat visit does not carry it into a new session.
  useEffect(() => {
    if (sessionId) draftRef.current = undefined;
  }, [sessionId]);

  // If no sessionId in URL, auto-create one and redirect.
  useEffect(() => {
    if (sessionId || startedRef.current) return;
    startedRef.current = true;
    startSession();
  }, [sessionId, startSession]);

  // The draft only needs to survive the redirect. Clear it from history once
  // the panel has it, so a reload or Back does not refill text already sent.
  useEffect(() => {
    if ((sessionId || error) && draft) navigate(location.pathname, { replace: true, state: null });
  }, [sessionId, error, draft, navigate, location.pathname]);

  if (sessionId) return <ChatPanel sessionId={sessionId} initialDraft={draft} />;

  return (
    <div className={styles.statusPane}>
      {error ? (
        <>
          <p className={styles.statusMessage} role="alert">
            {error}
          </p>
          {keptDraft ? (
            <p className={styles.statusMessage}>Your text is kept: &ldquo;{keptDraft}&rdquo;</p>
          ) : null}
          <button type="button" className={styles.retryButton} onClick={startSession}>
            Try again
          </button>
        </>
      ) : (
        <p className={styles.statusMessage} role="status">
          Creating chat…
        </p>
      )}
    </div>
  );
}
