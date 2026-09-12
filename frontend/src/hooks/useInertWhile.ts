import { RefObject, useEffect } from 'react';

// Applies background inertness to a fixed set of caller-owned nodes while
// `isActive` is true, and removes it on deactivation and on unmount.
//
// Deliberately takes refs, not selectors — the caller must own the nodes it
// hides, so it can never accidentally inert an element it doesn't control
// (e.g. the drawer's own close control).
//
// Falls back to aria-hidden when the `inert` attribute is unsupported
// (older Safari, some test environments). Never applies both at once —
// that would double-hide the same subtree to assistive tech.
//
// Non-goal: this is background inertness, not a focus trap. Dismissal
// paths (Esc, scrim, hamburger, route change) remain the trap-avoidance
// mechanism; useInertWhile only keeps focus from wandering into
// `<main>` while a modal surface is open.
export function useInertWhile(isActive: boolean, refs: RefObject<HTMLElement>[]): void {
  useEffect(() => {
    if (!isActive) return undefined;

    const elements = refs
      .map((ref) => ref.current)
      .filter((el): el is HTMLElement => el !== null);

    const supportsInert = elements.length > 0 && 'inert' in elements[0];

    elements.forEach((el) => {
      if (supportsInert) {
        el.setAttribute('inert', '');
      } else {
        el.setAttribute('aria-hidden', 'true');
      }
    });

    return () => {
      elements.forEach((el) => {
        el.removeAttribute('inert');
        el.removeAttribute('aria-hidden');
      });
    };
    // refs is a stable array of ref objects across renders; only isActive
    // should re-trigger this effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isActive]);
}
