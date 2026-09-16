import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { useCallback, useEffect, useState } from 'react';

import { ChatPanel } from '../chat/ChatPanel';
import { CHAT_PATH, type ChatLocationState } from '../routes/paths';
import { MissingTokenError, createChatSession } from '../chat/chatApi';
import styles from './Chat.module.css';

export default function Chat() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);

  const draft = (location.state as ChatLocationState | null)?.draft;

  const startSession = useCallback(() => {
    setError(null);
    createChatSession()
      .then((session) =>
        // Carry the draft across the auto-create redirect so a Quick
        // Capture submission survives landing on the freshly created
        // session's URL.
        navigate(`${CHAT_PATH}/${session.id}`, {
          replace: true,
          state: draft ? { draft } : null,
        }),
      )
      .catch((err) =>
        setError(
          err instanceof MissingTokenError
            ? 'You need to sign in again before starting a chat.'
            : 'Could not start a new chat session.',
        ),
      );
  }, [navigate, draft]);

  // If no sessionId in URL, auto-create one and redirect.
  useEffect(() => {
    if (sessionId) return;
    startSession();
  }, [sessionId, startSession]);

  if (sessionId) return <ChatPanel sessionId={sessionId} initialDraft={draft} />;

  return (
    <div className={styles.statusPane}>
      {error ? (
        <>
          <p className={styles.statusMessage} role="alert">
            {error}
          </p>
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
