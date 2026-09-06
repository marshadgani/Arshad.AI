import '@testing-library/jest-dom/vitest';

// jsdom does not implement matchMedia. The stub below is query-aware: it
// parses the `(max-width: Npx)` / `(min-width: Npx)` value out of the query
// string and compares it against the current (mocked) window width, rather
// than returning a fixed boolean. A stub that ignores the query would make
// mobile and desktop tests pass identically — exactly the failure mode that
// let a frozen-desktop-with-aria-modal bug reach production.

type Listener = (event: MediaQueryListEvent) => void;

const listenersByQuery = new Map<string, Set<Listener>>();

function parseThreshold(query: string): { type: 'max' | 'min'; px: number } | null {
  const max = query.match(/\(max-width:\s*([\d.]+)px\)/);
  if (max) return { type: 'max', px: parseFloat(max[1]) };
  const min = query.match(/\(min-width:\s*([\d.]+)px\)/);
  if (min) return { type: 'min', px: parseFloat(min[1]) };
  return null;
}

function matchesQuery(query: string, width: number): boolean {
  const threshold = parseThreshold(query);
  if (!threshold) return false;
  return threshold.type === 'max' ? width <= threshold.px : width >= threshold.px;
}

function installMatchMedia() {
  window.matchMedia = ((query: string) => {
    const mql = {
      get matches() {
        return matchesQuery(query, window.innerWidth);
      },
      media: query,
      onchange: null,
      addListener: (listener: Listener) => mql.addEventListener('change', listener),
      removeListener: (listener: Listener) => mql.removeEventListener('change', listener),
      addEventListener: (_type: string, listener?: Listener) => {
        const fn = typeof _type === 'function' ? (_type as unknown as Listener) : listener;
        if (!fn) return;
        if (!listenersByQuery.has(query)) listenersByQuery.set(query, new Set());
        listenersByQuery.get(query)!.add(fn);
      },
      removeEventListener: (_type: string, listener?: Listener) => {
        const fn = typeof _type === 'function' ? (_type as unknown as Listener) : listener;
        if (!fn) return;
        listenersByQuery.get(query)?.delete(fn);
      },
      dispatchEvent: () => false,
    } as unknown as MediaQueryList;
    return mql;
  }) as unknown as typeof window.matchMedia;
}

installMatchMedia();

// Sets window.innerWidth and notifies every registered MediaQueryList
// listener so useMediaQuery's subscription path (not just its initial
// read) is exercised by tests.
export function setViewport(width: number): void {
  Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: width });
  listenersByQuery.forEach((listeners, query) => {
    const event = { matches: matchesQuery(query, width), media: query } as MediaQueryListEvent;
    listeners.forEach((listener) => listener(event));
  });
  window.dispatchEvent(new Event('resize'));
}

// Desktop by default so any test that does not opt in behaves exactly as
// it did before this harness existed.
beforeEach(() => {
  setViewport(1280);
});

// jsdom does not implement Element.scrollTo (used by ChatPanel's autoscroll).
if (typeof Element !== 'undefined' && !Element.prototype.scrollTo) {
  Element.prototype.scrollTo = () => undefined;
}
