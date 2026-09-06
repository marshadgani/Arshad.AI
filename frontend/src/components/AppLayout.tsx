import { ReactNode, useEffect, useRef } from 'react';

import ChatLauncher, { useChatLauncherVisible } from './ChatLauncher';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import { useDisclosure } from '../hooks/useDisclosure';
import { useInertWhile } from '../hooks/useInertWhile';
import { useIsMobile } from '../hooks/useBreakpoint';
import styles from './AppLayout.module.css';

export interface AppLayoutProps {
  children: ReactNode;
}

// Sole owner of the mobile/desktop breakpoint subscription and of every
// cross-component modal effect it drives — this is the only component that
// actually renders Sidebar, TopBar and <main>, so it is the only place that
// can safely reach across them.
export default function AppLayout({ children }: AppLayoutProps) {
  const nav = useDisclosure();
  const overlayMode = useIsMobile();
  const showLauncher = useChatLauncherVisible(nav.isOpen);
  const mainRef = useRef<HTMLElement>(null);

  // A drawer left open across a mobile-to-desktop transition (e.g. device
  // rotation) would otherwise survive the scrim unmounting and permanently
  // hide the FAB, since useChatLauncherVisible gates on nav.isOpen.
  const wasOverlay = useRef(overlayMode);
  useEffect(() => {
    if (wasOverlay.current && !overlayMode) {
      nav.close();
    }
    wasOverlay.current = overlayMode;
  }, [overlayMode, nav]);

  // The drawer is only a true modal while it is both open and rendered as
  // an overlay (mobile). On desktop it is a persistent landmark and must
  // never make the rest of the page inert.
  const isNavModal = nav.isOpen && overlayMode;
  useInertWhile(isNavModal, [mainRef]);

  const contentClass = showLauncher
    ? `${styles.content} ${styles.contentFabPad}`
    : styles.content;

  return (
    <div className={styles.app}>
      <Sidebar isOpen={nav.isOpen} onClose={nav.close} overlayMode={overlayMode} />
      <TopBar onMenuClick={nav.toggle} isNavOpen={nav.isOpen} />
      <main ref={mainRef} className={styles.main}>
        <div className={contentClass}>{children}</div>
      </main>
      <ChatLauncher isNavOpen={nav.isOpen} />
    </div>
  );
}
