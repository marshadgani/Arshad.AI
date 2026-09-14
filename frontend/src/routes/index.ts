// Public surface of the routing module: the path literals every consumer
// shares, plus the typed router-state contracts that travel between
// routes. Import from '../routes', not from the files inside it, so the
// module has one entry point to change.
//
// `export *` for paths deliberately: it is a flat list of constants, and
// re-listing each one here would make adding a path a two-file edit whose
// second half is easy to forget.
export * from './paths';
export { chatDraftState, readChatDraft } from './chatDraft';
export type { ChatDraftState } from './chatDraft';
