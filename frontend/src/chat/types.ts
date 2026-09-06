export interface PersistedMessageContent {
  text?: string;
  tool?: string;
  output?: unknown;
  is_error?: boolean;
}

export interface PersistedMessage {
  id: string;
  role: string;
  content: PersistedMessageContent;
  created_at: string | null;
}
