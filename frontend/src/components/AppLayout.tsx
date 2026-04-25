import { ReactNode } from 'react';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import ChatBar from './ChatBar';
import styles from './AppLayout.module.css';

export interface AppLayoutProps {
  children: ReactNode;
}

export default function AppLayout({ children }: AppLayoutProps) {
  return (
    <div className={styles.app}>
      <Sidebar />
      <TopBar />
      <main className={styles.main}>
        <div className={styles.content}>{children}</div>
      </main>
      <ChatBar />
    </div>
  );
}
