import { ReactNode, useState } from 'react';
import { useLocation } from 'react-router-dom';

import ChatLauncher from './ChatLauncher';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import styles from './AppLayout.module.css';

export interface AppLayoutProps {
  children: ReactNode;
}

export default function AppLayout({ children }: AppLayoutProps) {
  const [isNavOpen, setNavOpen] = useState(false);
  const { pathname } = useLocation();
  const isChatRoute = pathname.startsWith('/chat');
  const showLauncher = !isChatRoute && !isNavOpen;

  return (
    <div className={styles.app}>
      <Sidebar isOpen={isNavOpen} onClose={() => setNavOpen(false)} />
      <TopBar onMenuClick={() => setNavOpen((v) => !v)} isNavOpen={isNavOpen} />
      <main className={styles.main}>
        <div className={showLauncher ? `${styles.content} ${styles.contentFabPad}` : styles.content}>
          {children}
        </div>
      </main>
      <ChatLauncher isNavOpen={isNavOpen} />
    </div>
  );
}
