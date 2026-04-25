import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

import { useAuth } from '../auth/AuthContext';

// Backend redirects to /auth/callback#token=<jwt>. Reading from the URL
// FRAGMENT (not the query string) keeps the JWT out of server logs and
// out of the Referer header on the next navigation.
export default function AuthCallback() {
  const { setTokenFromCallback } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    const fragment = window.location.hash.replace(/^#/, '');
    const params = new URLSearchParams(fragment);
    const token = params.get('token');
    if (token) {
      setTokenFromCallback(token);
      window.history.replaceState(null, '', '/');
      navigate('/', { replace: true });
    } else {
      navigate('/login', { replace: true });
    }
  }, [navigate, setTokenFromCallback]);

  return <div style={{ padding: '2rem', color: '#8b949e' }}>Signing you in…</div>;
}
