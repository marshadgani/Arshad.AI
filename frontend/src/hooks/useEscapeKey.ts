import { useEffect } from 'react';

// Invokes `onEscape` while `isActive`. Inactive means no listener is
// attached at all, so a closed or non-modal surface costs nothing.
export function useEscapeKey(isActive: boolean, onEscape: () => void): void {
  useEffect(() => {
    if (!isActive) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onEscape();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isActive, onEscape]);
}
