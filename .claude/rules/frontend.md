# Frontend Rules — React + TypeScript

## Components

- **Functional components only.** No class components, ever.
- **One component per file.** The file name matches the component name exactly (`ChatInput.tsx` exports `ChatInput`).
- **Co-locate related files.** Component, its styles, and its tests live in the same directory.
  ```
  components/
    ChatInput/
      ChatInput.tsx
      ChatInput.module.css
      ChatInput.test.tsx
      index.ts          ← re-exports ChatInput as the public API
  ```
- **Props interfaces** are defined in the same file, named `<ComponentName>Props`, and exported.
- **No default export for utilities** — only components use default exports.

## TypeScript

- Strict mode is on. No `any`, no `// @ts-ignore` without an explanatory comment.
- Prefer `type` over `interface` for simple shapes. Use `interface` for objects that may be extended.
- Enum alternatives: use `as const` objects instead of TypeScript enums.
  ```ts
  // Preferred
  const MessageRole = { User: 'user', Assistant: 'assistant' } as const;
  type MessageRole = typeof MessageRole[keyof typeof MessageRole];
  ```

## State Management

- **Local state first** — `useState` and `useReducer` for component-scoped state.
- **Context** only for genuinely global state (auth, theme). Keep contexts small and focused.
- **No Redux** unless the team decides otherwise — it's overkill for this project size.
- Derived values are computed from state, not stored in state.

## Hooks

- Custom hooks are prefixed `use` and live in `frontend/src/hooks/`.
- A hook that fetches data returns `{ data, isLoading, error }` — consistent across the app.
- Never call hooks conditionally. If conditional behaviour is needed, handle it inside the hook.

## Styling

- CSS Modules (`.module.css`) for component styles. No global CSS except `index.css` for resets.
- No inline `style` props except for genuinely dynamic values (e.g. calculated widths).
- Class names use camelCase in CSS Modules (`styles.chatBubble`).
- Colours and spacing come from CSS variables defined in `index.css`. No hardcoded hex values.

## Performance

- `React.memo` only when a component provably re-renders unnecessarily — measure first.
- `useMemo` / `useCallback` only for expensive computations or stable references passed to memoised children.
- Lazy-load heavy routes with `React.lazy` + `Suspense`.
- Images use explicit `width` and `height` to prevent layout shift.

## Testing

- Use React Testing Library. Query by role and label, not by CSS class or test ID.
- Every interactive component (forms, buttons, inputs) must have at least one integration test.
- Snapshot tests are banned — they break constantly and rarely catch real bugs.
