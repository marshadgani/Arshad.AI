import { RefObject, useEffect, useRef } from 'react';

import { useChatLauncherVisible } from './useChatLauncherVisible';
import { useDisclosure } from './useDisclosure';
import { useInertWhile } from './useInertWhile';
import { useIsMobile } from './useBreakpoint';

export interface AppShell {
  /** Nav drawer open state. */
  isNavOpen: boolean;
  toggleNav: () => void;
  closeNav: () => void;
  /** True below the mobile breakpoint, where the drawer is an overlay. */
  overlayMode: boolean;
  /** True while the FAB occupies the bottom-right corner. */
  showLauncher: boolean;
}

export interface AppShellOptions {
  /** The content region to make inert while the drawer is a modal. */
  contentRef: RefObject<HTMLElement>;
}

// Owns every piece of app-shell state that spans Sidebar, TopBar and the
// content region: the single breakpoint subscription, nav disclosure, the
// modal-vs-landmark distinction the drawer derives from it, and the
// cross-component effects that follow (background inertness, drawer close
// on rotation).
//
// Extracted from AppLayout so that layout markup and shell behaviour can be
// reviewed, tested and changed independently. AppLayout is now composition
// only; this hook is the only place that reads the viewport.
export function useAppShell({ contentRef }: AppShellOptions): AppShell {
  const nav = useDisclosure();
  const overlayMode = useIsMobile();
  const showLauncher = useChatLauncherVisible(nav.isOpen);

  // A drawer left open across a mobile-to-desktop transition (e.g. device
  // rotation) would otherwise survive the scrim unmounting and permanently
  // hide the FAB, since useChatLauncherVisible gates on nav.isOpen.
  const wasOverlay = useRef(overlayMode);
  const closeNav = nav.close;
  useEffect(() => {
    if (wasOverlay.current && !overlayMode) {
      closeNav();
    }
    wasOverlay.current = overlayMode;
  }, [overlayMode, closeNav]);

  // The drawer is only a true modal while it is both open and rendered as
  // an overlay (mobile). On desktop it is a persistent landmark and must
  // never make the rest of the page inert.
  const isNavModal = nav.isOpen && overlayMode;
  useInertWhile(isNavModal, [contentRef]);

  return {
    isNavOpen: nav.isOpen,
    toggleNav: nav.toggle,
    closeNav: nav.close,
    overlayMode,
    showLauncher,
  };
}
