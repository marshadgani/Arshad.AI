import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { useCallback, useEffect, useState } from 'react';

import { ChatPanel } from '../chat/ChatPanel';
import { CHAT_PATH, chatDraftState, readChatDraft } from '../routes';
import { MissingTokenError, createChatSession } from '../chat/chatApi';
import styles from './Chat.module.css';

export default function Chat() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);

  // Quick Capture (TopBar) navigates here with { state: { draft } }. The
  // auto-create redirect below used to drop router state entirely — carry
  // it through so the draft survives the /chat -> /chat/:id boundary.
  const draft = readChatDraft(location.state);

  const startSession = useCallback(() => {
    setError(null);
    createChatSession()
      .then((session) =>
        navigate(`${CHAT_PATH}/${session.id}`, {
          replace: true,
          state: draft ? chatDraftState(draft) : null,
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
