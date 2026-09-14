// Route literals that more than one module needs to reason about. Keeping
// them here stops `pathname.startsWith('/chat')` from being re-typed at each
// call site, where a rename would silently miss one.

export const CHAT_PATH = '/chat';
export const INTEGRATIONS_PATH = '/integrations';
export const SETTINGS_PATH = '/settings';
export const ACTIVITY_LOG_PATH = '/activity-log';

export function isChatPath(pathname: string): boolean {
  return pathname.startsWith(CHAT_PATH);
}
