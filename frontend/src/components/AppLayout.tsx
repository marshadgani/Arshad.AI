import { ReactNode, useRef } from 'react';

import ChatLauncher from './ChatLauncher';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import { useAppShell } from '../hooks/useAppShell';
import styles from './AppLayout.module.css';

export interface AppLayoutProps {
  children: ReactNode;
}

// Composition only: it arranges the shell's three regions and hands each
// the slice of shell state it needs. All behaviour — the breakpoint
// subscription, drawer disclosure, background inertness and the
// rotation-close repair — lives in useAppShell.
export default function AppLayout({ children }: AppLayoutProps) {
  const mainRef = useRef<HTMLElement>(null);
  const shell = useAppShell({ contentRef: mainRef });

  const contentClass = shell.showLauncher
    ? `${styles.content} ${styles.contentFabPad}`
    : styles.content;

  return (
    <div className={styles.app}>
      <Sidebar
        isOpen={shell.isNavOpen}
        onClose={shell.closeNav}
        overlayMode={shell.overlayMode}
      />
      <TopBar onMenuClick={shell.toggleNav} isNavOpen={shell.isNavOpen} />
      <main ref={mainRef} className={styles.main}>
        <div className={contentClass}>{children}</div>
      </main>
      <ChatLauncher isNavOpen={shell.isNavOpen} />
    </div>
  );
}
