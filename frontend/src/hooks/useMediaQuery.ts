import { useEffect, useState } from 'react';

// Generic media-query primitive. It deliberately knows nothing about this
// app's breakpoints — that mapping lives in useBreakpoint.ts so the two can
// change independently.

// jsdom (and any SSR context) has no matchMedia — guard so the hook is safe
// to call unconditionally in tests and never throws during render.
function getMatches(query: string): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia(query).matches;
}

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(() => getMatches(query));

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  }, [query]);

  return matches;
}
