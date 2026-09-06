import { Link, useLocation } from 'react-router-dom';

import styles from './ChatLauncher.module.css';

export interface ChatLauncherProps {
  isNavOpen: boolean;
}

export default function ChatLauncher({ isNavOpen }: ChatLauncherProps) {
  const { pathname } = useLocation();
  const isChatRoute = pathname.startsWith('/chat');

  // Never overlay the chat surface it links to, and never fight the nav
  // drawer for the user's attention while it's open.
  if (isChatRoute || isNavOpen) return null;

  return (
    <Link to="/chat" className={styles.fab} aria-label="Open Arshad.AI chat">
      ✶
    </Link>
  );
}
