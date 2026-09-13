import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

import { useAuth } from '../auth/AuthContext';
import styles from './AuthCallback.module.css';

// Backend redirects to /auth/callback#token=<jwt>. Reading from the URL
// FRAGMENT (not the query string) keeps the JWT out of server logs and
// out of the Referer header on the next navigation.
//
// An `error` code (same fragment) is forwarded to Login as a query param —
// not router state — so it survives a hard navigation/refresh at this URL
// and so Login can read it without depending on a <Router> context in
// isolation. See Login.tsx's ERROR_MESSAGES map for the codes this covers.
export default function AuthCallback() {
  const { setTokenFromCallback } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    const fragment = window.location.hash.replace(/^#/, '');
    const params = new URLSearchParams(fragment);
    const token = params.get('token');
    const errorCode = params.get('error');
    if (token) {
      setTokenFromCallback(token);
      window.history.replaceState(null, '', '/');
      navigate('/', { replace: true });
    } else if (errorCode) {
      navigate(`/login?error=${encodeURIComponent(errorCode)}`, { replace: true });
    } else {
      navigate('/login', { replace: true });
    }
  }, [navigate, setTokenFromCallback]);

  return (
    <div className={styles.statusMessage} role="status" aria-live="polite">
      Signing you in…
    </div>
  );
}
