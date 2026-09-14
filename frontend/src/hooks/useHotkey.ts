import { useEffect, useRef } from 'react';

export interface HotkeyOptions {
  /** Require Cmd (macOS) or Ctrl (elsewhere). */
  meta?: boolean;
}

/**
 * Fires `onFire` when `key` is pressed globally, while `isActive`.
 *
 * Sibling of useEscapeKey: same "inactive means no listener is attached at
 * all" contract, generalised to an arbitrary key plus the Cmd/Ctrl
 * modifier. It exists so a component that wants a shortcut declares the
 * shortcut, rather than hand-rolling another window keydown effect with
 * its own preventDefault and platform-modifier check — the detail most
 * easily got wrong (`e.metaKey || e.ctrlKey`, and lower-casing `e.key`
 * so Shift+Cmd+K still matches).
 *
 * `onFire` is held in a ref, so an inline arrow at the call site does not
 * resubscribe the listener on every render.
 */
export function useHotkey(
  isActive: boolean,
  key: string,
  onFire: () => void,
  { meta = false }: HotkeyOptions = {},
): void {
  const onFireRef = useRef(onFire);
  onFireRef.current = onFire;

  useEffect(() => {
    if (!isActive) return undefined;

    const target = key.toLowerCase();
    const onKeyDown = (e: KeyboardEvent) => {
      if (meta && !(e.metaKey || e.ctrlKey)) return;
      if (e.key.toLowerCase() !== target) return;
      e.preventDefault();
      onFireRef.current();
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isActive, key, meta]);
}
