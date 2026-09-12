import { Link } from 'react-router-dom';

import { CHAT_PATH } from '../../routes/paths';
import { useChatLauncherVisible } from '../../hooks/useChatLauncherVisible';
import styles from './ChatLauncher.module.css';

export interface ChatLauncherProps {
  isNavOpen: boolean;
}

// Presentation only. The visibility rule is shared with the shell, so it
// lives in hooks/useChatLauncherVisible rather than here.
export default function ChatLauncher({ isNavOpen }: ChatLauncherProps) {
  const isVisible = useChatLauncherVisible(isNavOpen);
  if (!isVisible) return null;

  return (
    <Link to={CHAT_PATH} className={styles.fab} aria-label="Open Arshad.AI chat">
      ✶
    </Link>
  );
}
