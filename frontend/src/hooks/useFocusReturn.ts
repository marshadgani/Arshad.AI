import { RefObject, useEffect, useRef } from 'react';

// Modal focus choreography: move focus into `targetRef` when the surface
// opens, and hand it back to whatever element opened it (the hamburger
// button) when it closes. Disabled entirely when `isEnabled` is false —
// a persistent desktop landmark must not steal focus.
export function useFocusReturn(
  isEnabled: boolean,
  isOpen: boolean,
  targetRef: RefObject<HTMLElement>,
): void {
  const priorFocusRef = useRef<Element | null>(null);

  useEffect(() => {
    if (!isEnabled) return;
    if (isOpen) {
      priorFocusRef.current = document.activeElement;
      targetRef.current?.focus();
    } else if (priorFocusRef.current instanceof HTMLElement) {
      priorFocusRef.current.focus();
    }
    // targetRef is a stable ref object; re-running on its identity would be
    // a no-op at best and a focus-steal at worst.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isEnabled, isOpen]);
}
