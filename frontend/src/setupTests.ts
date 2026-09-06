import '@testing-library/jest-dom/vitest';

// jsdom does not implement matchMedia. Stub it so useMediaQuery is
// drivable per test via query-string matching on a fixed viewport.
if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }) as unknown as MediaQueryList;
}

// jsdom does not implement Element.scrollTo (used by ChatPanel's autoscroll).
if (typeof Element !== 'undefined' && !Element.prototype.scrollTo) {
  Element.prototype.scrollTo = () => undefined;
}
