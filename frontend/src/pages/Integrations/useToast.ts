import { useCallback, useEffect, useRef, useState } from 'react';

const TOAST_MS = 3000;

/**
 * Transient status message shown at the bottom of the page.
 *
 * The inline version leaked its timer: every flash scheduled a bare
 * setTimeout with no clear on the next flash or on unmount, so rapid
 * actions could race each other's dismissals and a timer could fire
 * after the page had gone. Owning the timer in one hook makes both
 * cases impossible without any caller having to think about it.
 */
export function useToast() {
  const [toast, setToast] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);

  const clearTimer = () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const flashToast = useCallback((message: string) => {
    clearTimer();
    setToast(message);
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      setToast(null);
    }, TOAST_MS);
  }, []);

  useEffect(() => clearTimer, []);

  return { toast, flashToast };
}
