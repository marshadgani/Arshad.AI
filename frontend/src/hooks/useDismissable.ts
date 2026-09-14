import { RefObject, useEffect, useRef } from 'react';

import { useEscapeKey } from './useEscapeKey';

/**
 * Dismiss + focus choreography for a popover/menu surface, shared by every
 * TopBar popover (NotificationsPanel, AccountMenu) so the behaviour is
 * implemented exactly once.
 *
 * Composes useEscapeKey and adds:
 * - outside-`pointerdown` dismissal. Deliberately `pointerdown`, not
 *   `click`: `click` fires AFTER the trigger button's own onClick, so a
 *   bare click-outside listener would close the popover and then the
 *   trigger's toggle handler would immediately reopen it.
 * - the outside check also excludes `triggerRef`, so the trigger's own
 *   click is the only thing allowed to close what it just opened.
 * - focus-in on open (to `focusTargetRef ?? containerRef`) and focus-return
 *   to the trigger on close, but ONLY if the closing surface still owned
 *   focus — so closing never yanks focus off whatever the user just moved
 *   it to (e.g. clicking a link outside the popover). Swapping directly
 *   from one popover to another is safe: React flushes every effect
 *   cleanup before any effect setup, so the newly opened surface's own
 *   focus call runs last and wins.
 */
export function useDismissable(
  isOpen: boolean,
  onClose: () => void,
  containerRef: RefObject<HTMLElement>,
  triggerRef: RefObject<HTMLElement>,
  focusTargetRef?: RefObject<HTMLElement>,
): void {
  useEscapeKey(isOpen, onClose);

  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!isOpen) return undefined;

    const handlePointerDown = (e: PointerEvent) => {
      const target = e.target as Node | null;
      if (!target) return;
      if (containerRef.current?.contains(target)) return;
      if (triggerRef.current?.contains(target)) return;
      onCloseRef.current();
    };
    document.addEventListener('pointerdown', handlePointerDown);
    return () => document.removeEventListener('pointerdown', handlePointerDown);
  }, [isOpen, containerRef, triggerRef]);

  useEffect(() => {
    if (!isOpen) return undefined;
    (focusTargetRef?.current ?? containerRef.current)?.focus();

    return () => {
      // By the time this passive cleanup runs, the closing surface's DOM is
      // already gone and `containerRef.current` is null — so "is focus still
      // inside the container?" can never be answered by containment alone.
      // Removing the focused node leaves focus on <body>, and THAT is the
      // signal that the closing surface owned it. Anything else (the user
      // clicked a link, a button, another input) owns focus legitimately and
      // must not be yanked back to the trigger.
      const active = document.activeElement;
      const surfaceOwnedFocus =
        !active || active === document.body || containerRef.current?.contains(active) === true;
      if (surfaceOwnedFocus) {
        triggerRef.current?.focus();
      }
    };
    // Refs are stable objects; re-running on identity is a no-op at best.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);
}
