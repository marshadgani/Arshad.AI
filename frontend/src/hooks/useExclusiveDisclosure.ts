import { useCallback, useMemo, useState } from 'react';

export interface ExclusiveDisclosure<Id extends string> {
  /** The currently open surface, or null when all are closed. */
  openId: Id | null;
  isOpen: (id: Id) => boolean;
  /** Opens `id`, or closes it if it is already the open one. */
  toggle: (id: Id) => void;
  close: () => void;
}

/**
 * useDisclosure's one-of-N sibling: a group of surfaces (popovers, menus)
 * of which at most one may be open.
 *
 * Holding a single `Id | null` rather than one boolean per surface makes
 * mutual exclusion structural instead of conventional — with N booleans,
 * "close the others" is a rule every new trigger has to remember, and the
 * illegal all-open state stays representable.
 *
 * `toggle` and `close` are referentially stable, so they can be passed
 * straight to children and into effect dependency arrays.
 */
export function useExclusiveDisclosure<Id extends string>(): ExclusiveDisclosure<Id> {
  const [openId, setOpenId] = useState<Id | null>(null);

  const toggle = useCallback((id: Id) => {
    setOpenId((current) => (current === id ? null : id));
  }, []);
  const close = useCallback(() => setOpenId(null), []);
  const isOpen = useCallback((id: Id) => openId === id, [openId]);

  return useMemo(
    () => ({ openId, isOpen, toggle, close }),
    [openId, isOpen, toggle, close],
  );
}
