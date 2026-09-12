import { useEffect, useRef } from 'react';

// Prevents the page behind a full-viewport overlay from scrolling.
// The prior overflow value is captured on lock and restored on unlock, so a
// viewport resize that deactivates the lock mid-open cannot strand the body
// in `overflow: hidden`.
export function useBodyScrollLock(isLocked: boolean): void {
  const priorOverflowRef = useRef<string>('');

  useEffect(() => {
    if (!isLocked) return;
    priorOverflowRef.current = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = priorOverflowRef.current;
    };
  }, [isLocked]);
}
