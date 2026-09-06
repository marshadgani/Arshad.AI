import { ReactNode } from 'react';

import ChatLauncher, { useChatLauncherVisible } from './ChatLauncher';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import { useDisclosure } from '../hooks/useDisclosure';
import styles from './AppLayout.module.css';

export interface AppLayoutProps {
  children: ReactNode;
}

// Pure composition: chrome placement plus the one piece of state the chrome
// shares (whether the nav drawer is open). Drawer mechanics live in
// useDisclosure, FAB visibility in useChatLauncherVisible.
export default function AppLayout({ children }: AppLayoutProps) {
  const nav = useDisclosure();
  const showLauncher = useChatLauncherVisible(nav.isOpen);

  const contentClass = showLauncher
    ? `${styles.content} ${styles.contentFabPad}`
    : styles.content;

  return (
    <div className={styles.app}>
      <Sidebar isOpen={nav.isOpen} onClose={nav.close} />
      <TopBar onMenuClick={nav.toggle} isNavOpen={nav.isOpen} />
      <main className={styles.main}>
        <div className={contentClass}>{children}</div>
      </main>
      <ChatLauncher isNavOpen={nav.isOpen} />
    </div>
  );
}
