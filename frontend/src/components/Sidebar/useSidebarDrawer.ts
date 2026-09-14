import { useRef } from 'react';
import type { RefObject } from 'react';

import { useBodyScrollLock } from '../../hooks/useBodyScrollLock';
import { useEscapeKey } from '../../hooks/useEscapeKey';
import { useFocusReturn } from '../../hooks/useFocusReturn';
import { useOnRouteChange } from '../../hooks/useOnRouteChange';

interface DialogProps {
  role: 'dialog';
  'aria-modal': true;
  'aria-label': string;
  tabIndex: -1;
}

export interface UseSidebarDrawerResult {
  /** Attach to the sidebar element — focus management targets it. */
  asideRef: RefObject<HTMLElement>;
  /** True only while the sidebar is an open mobile overlay. */
  isModal: boolean;
  /** Spread onto the sidebar element; empty unless it is a modal. */
  dialogProps: Partial<DialogProps>;
}

// Owns every "the sidebar is behaving as a modal drawer" concern — escape to
// close, body scroll lock, focus return, close-on-navigate, dialog ARIA — so
// Sidebar.tsx stays pure markup. All of it hangs off the one `isModal`
// predicate, derived from the overlayMode that useAppShell supplies, so
// neither this hook nor Sidebar ever reads the viewport itself.
export function useSidebarDrawer(
  isOpen: boolean,
  onClose: () => void,
  overlayMode: boolean,
): UseSidebarDrawerResult {
  const asideRef = useRef<HTMLElement>(null);
  const isModal = isOpen && overlayMode;

  useOnRouteChange(() => {
    if (isOpen) onClose();
  });
  useEscapeKey(isModal, onClose);
  useBodyScrollLock(isModal);
  useFocusReturn(overlayMode, isOpen, asideRef);

  // Gating on overlayMode alone would leave aria-modal="true" on the closed,
  // off-canvas drawer, telling assistive tech the rest of the page is inert
  // while nothing is visually blocking it.
  const dialogProps: Partial<DialogProps> = isModal
    ? {
        role: 'dialog',
        'aria-modal': true,
        'aria-label': 'Main navigation',
        tabIndex: -1,
      }
    : {};

  return { asideRef, isModal, dialogProps };
}
