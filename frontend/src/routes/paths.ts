// Route literals that more than one module needs to reason about. Keeping
// them here stops `pathname.startsWith('/chat')` from being re-typed at each
// call site, where a rename would silently miss one.

export const CHAT_PATH = '/chat';
export const SETTINGS_PATH = '/settings';

export function isChatPath(pathname: string): boolean {
  return pathname.startsWith(CHAT_PATH);
}

// Router `state` shape shared between the writer (TopBar's Quick Capture)
// and the reader (Chat.tsx) so both sides cast to the same type instead of
// each guessing an inline shape.
export interface ChatLocationState {
  draft?: string;
}
