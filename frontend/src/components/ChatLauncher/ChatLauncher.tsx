import { Link, useLocation } from 'react-router-dom';

import { isChatPath, CHAT_PATH } from '../../routes/paths';
import styles from './ChatLauncher.module.css';

export interface ChatLauncherProps {
  isNavOpen: boolean;
}

// Single source of truth for whether the FAB is on screen. AppLayout uses it
// to reserve bottom padding; ChatLauncher uses it to decide whether to
// render. Previously each re-derived the rule, so they could drift apart.
export function useChatLauncherVisible(isNavOpen: boolean): boolean {
  const { pathname } = useLocation();
  // Never overlay the chat surface it links to, and never fight the nav
  // drawer for the user's attention while it's open.
  return !isChatPath(pathname) && !isNavOpen;
}

export default function ChatLauncher({ isNavOpen }: ChatLauncherProps) {
  const isVisible = useChatLauncherVisible(isNavOpen);
  if (!isVisible) return null;

  return (
    <Link to={CHAT_PATH} className={styles.fab} aria-label="Open Arshad.AI chat">
      ✶
    </Link>
  );
}
