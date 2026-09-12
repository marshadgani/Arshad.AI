import { useLocation } from 'react-router-dom';

import { isChatPath } from '../routes/paths';

// Single source of truth for whether the chat FAB is on screen.
//
// It lives here, not inside ChatLauncher, because two unrelated consumers
// need the answer: the shell reserves bottom padding for the FAB, and
// ChatLauncher decides whether to render at all. Owning the rule in the
// component made the layout import a leaf's internals, which is the wrong
// direction of dependency and let the two derivations drift apart.
export function useChatLauncherVisible(isNavOpen: boolean): boolean {
  const { pathname } = useLocation();
  // Never overlay the chat surface it links to, and never fight the nav
  // drawer for the user's attention while it's open.
  return !isChatPath(pathname) && !isNavOpen;
}
