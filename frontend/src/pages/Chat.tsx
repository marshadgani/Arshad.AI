import { useNavigate, useParams } from 'react-router-dom';
import { useEffect } from 'react';

import { ChatPanel } from '../chat/ChatPanel';
import { getToken } from '../auth/tokenStorage';

export default function Chat() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();

  // If no sessionId in URL, auto-create one and redirect.
  useEffect(() => {
    if (sessionId) return;
    const token = getToken();
    if (!token) return;
    fetch('/api/v1/chat/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({}),
    })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((body) => navigate(`/chat/${body.data.id}`, { replace: true }))
      .catch(() => undefined);
  }, [sessionId, navigate]);

  if (!sessionId) {
    return <div style={{ padding: '2rem', color: '#8b949e' }}>Creating chat…</div>;
  }
  return <ChatPanel sessionId={sessionId} />;
}
