import { useEffect, type RefObject } from 'react';
import { useLocation } from 'react-router-dom';

// Closes an anchored, non-modal popover (a dropdown triggered from a TopBar
// icon button, not a full-screen modal) on Escape, on a click outside
// `containerRef`, or on route change. All three listeners attach only while
// `isOpen` is true, so a closed menu costs nothing. Does not move focus —
// focus stays on the trigger, which is the correct default for this kind
// of popover (contrast with a modal dialog, which traps focus).
export function useMenuDismiss(
  isOpen: boolean,
  close: () => void,
  containerRef: RefObject<HTMLElement>,
): void {
  const { pathname } = useLocation();

  useEffect(() => {
    if (!isOpen) return;

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    const onMouseDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        close();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    document.addEventListener('mousedown', onMouseDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('mousedown', onMouseDown);
    };
  }, [isOpen, close, containerRef]);

  useEffect(() => {
    if (!isOpen) return;
    close();
    // Only a pathname change should close the menu — not the isOpen flip
    // that opened it. Intentionally omitting isOpen/close from deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);
}
