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
  const draft = (location.state as { draft?: string } | null)?.draft;
  const [error, setError] = useState<string | null>(null);
  // The redirect must carry the newest captured text, but a changing draft
  // must never create a second session, so read it through a ref.
  const draftRef = useRef(draft);
  draftRef.current = draft;
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
        setError(
          err instanceof MissingTokenError
            ? 'You need to sign in again before starting a chat.'
            : 'Could not start a new chat session.',
        );
      });
  }, [navigate]);

  // If no sessionId in URL, auto-create one and redirect.
  useEffect(() => {
    if (sessionId || startedRef.current) return;
    startedRef.current = true;
    startSession();
  }, [sessionId, startSession]);

  // The draft only needs to survive the redirect. Clear it from history once
  // the panel has it, so a reload or Back does not refill text already sent.
  useEffect(() => {
    if (sessionId && draft) navigate(location.pathname, { replace: true, state: null });
  }, [sessionId, draft, navigate, location.pathname]);

  if (sessionId) return <ChatPanel sessionId={sessionId} initialDraft={draft} />;

  return (
    <div className={styles.statusPane}>
      {error ? (
        <>
          <p className={styles.statusMessage} role="alert">
            {error}
          </p>
          {draft ? (
            <p className={styles.statusMessage}>Your text is kept: &ldquo;{draft}&rdquo;</p>
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
