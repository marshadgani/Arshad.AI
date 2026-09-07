import { MessageBubble } from './MessageBubble';
import { ToolUseLine } from './ToolUseLine';
import type { PersistedMessage } from './types';

export interface MessageRowProps {
  message: PersistedMessage;
}

// Maps a persisted row onto the presentational primitive that renders it.
// It owns no styling of its own — that is the primitives' job.
export function MessageRow({ message }: MessageRowProps) {
  if (message.role === 'user' || message.role === 'assistant') {
    return <MessageBubble role={message.role}>{message.content.text}</MessageBubble>;
  }
  if (message.role === 'tool_use') {
    return <ToolUseLine toolName={message.content.tool} />;
  }
  // tool_result rows are not rendered separately; the assistant message
  // immediately following them carries the user-visible response.
  return null;
}
