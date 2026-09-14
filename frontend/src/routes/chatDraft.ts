// The Quick Capture -> Chat hand-off travels through react-router's
// `location.state`, which is typed `unknown`. Before this module, three
// call sites (TopBar's capture bar, pages/Chat.tsx, chat's own
// auto-create redirect) each re-declared the shape inline as
// `(location.state as { draft?: string } | null)?.draft`. That is an
// untyped, unenforced contract duplicated per consumer: renaming the key
// would type-check everywhere and silently drop the draft at runtime.
//
// Producing and reading the state now goes through this one pair of
// functions, so the key exists in exactly one place.

export interface ChatDraftState {
  draft: string;
}

/** Router state that carries `draft` into the chat route. */
export function chatDraftState(draft: string): ChatDraftState {
  return { draft };
}

/** Reads a draft back out of an opaque `location.state`, if present. */
export function readChatDraft(state: unknown): string | undefined {
  if (typeof state !== 'object' || state === null) return undefined;
  const draft = (state as Partial<ChatDraftState>).draft;
  return typeof draft === 'string' && draft.length > 0 ? draft : undefined;
}
