import { useCallback, useEffect, useRef, useState } from 'react';

type NavigationHandoff = {
  /** True between `start()` and whichever reset fires first. */
  isHandingOff: boolean;
  /** Runs `action` once; a call made while already handing off is a no-op. */
  start: (action: () => void) => void;
};

/**
 * Single-shot lock for an action that hands the browser to another origin
 * (an OAuth login redirect, a hosted-checkout handoff, …).
 *
 * The component that owns the button cannot solve this on its own: once the
 * browser leaves, nothing in React runs, so re-enabling has to be driven by
 * navigation events. Three independent resets, none of which the others can
 * substitute for:
 *   - pageshow(persisted): iOS Safari restores the page from the bfcache
 *     when the user taps back out of the destination.
 *   - timeout: covers everything pageshow doesn't (an error response, an
 *     unreachable destination, non-bfcache back navigation) so a failed
 *     attempt can never leave the control permanently disabled.
 *   - unmount cleanup: prevents a setState call after the component is gone.
 *
 * Extracted from Login so the lock is reusable and independently testable,
 * and so Login itself is left as presentation.
 */
export function useNavigationHandoff(resetAfterMs: number): NavigationHandoff {
  const [isHandingOff, setIsHandingOff] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearResetTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => {
    const handlePageShow = (event: PageTransitionEvent) => {
      if (event.persisted) {
        clearResetTimer();
        setIsHandingOff(false);
      }
    };
    window.addEventListener('pageshow', handlePageShow);
    return () => {
      window.removeEventListener('pageshow', handlePageShow);
      clearResetTimer();
    };
  }, [clearResetTimer]);

  const start = useCallback(
    (action: () => void) => {
      if (isHandingOff) return;
      setIsHandingOff(true);
      timerRef.current = setTimeout(() => setIsHandingOff(false), resetAfterMs);
      action();
    },
    [isHandingOff, resetAfterMs],
  );

  return { isHandingOff, start };
}
