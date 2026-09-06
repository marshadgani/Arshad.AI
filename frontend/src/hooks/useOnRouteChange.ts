import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';

// Runs `callback` whenever the pathname changes (and once on mount).
// The callback is held in a ref so callers may pass an inline closure
// without the effect re-firing on every render — only the route drives it.
export function useOnRouteChange(callback: () => void): void {
  const { pathname } = useLocation();
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    callbackRef.current();
  }, [pathname]);
}
