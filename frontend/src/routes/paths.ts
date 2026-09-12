// Route literals that more than one module needs to reason about. Keeping
// them here stops `pathname.startsWith('/chat')` from being re-typed at each
// call site, where a rename would silently miss one.

export const CHAT_PATH = '/chat';

export function isChatPath(pathname: string): boolean {
  return pathname.startsWith(CHAT_PATH);
}
