export type MessageRole = 'user' | 'assistant' | 'tool_use' | 'tool_result';

interface PersistedMessageBase {
  id: string;
  created_at: string | null;
}

// Discriminated on `role`, so a row can only carry the content fields that
// belong to it — one optional-everything bag let `{ role: 'assistant',
// content: { output } }` type-check. `text`/`tool` stay optional within a
// variant because older persisted rows can predate a field (see
// ToolUseLine's `toolName?`), not because any role may omit them.
export type PersistedMessage =
  | (PersistedMessageBase & { role: 'user' | 'assistant'; content: { text?: string } })
  | (PersistedMessageBase & { role: 'tool_use'; content: { tool?: string } })
  | (PersistedMessageBase & {
      role: 'tool_result';
      content: { tool?: string; output?: unknown; is_error?: boolean };
    });
