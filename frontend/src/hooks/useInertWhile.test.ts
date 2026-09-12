import { renderHook } from '@testing-library/react';
import { RefObject } from 'react';

import { useInertWhile } from './useInertWhile';

function makeRef(el: HTMLElement | null): RefObject<HTMLElement> {
  return { current: el };
}

// jsdom (as of this repo's pinned version) does not implement the `inert`
// IDL attribute, so the hook's aria-hidden fallback is what actually runs
// in this test environment — these tests exercise that path directly.
// A separate test simulates a browser that does support `inert`.

describe('useInertWhile', () => {
  it('sets aria-hidden on activate (jsdom has no inert support)', () => {
    const el = document.createElement('div');
    renderHook(() => useInertWhile(true, [makeRef(el)]));
    expect(el.getAttribute('aria-hidden')).toBe('true');
  });

  it('does not hide the element while inactive', () => {
    const el = document.createElement('div');
    renderHook(() => useInertWhile(false, [makeRef(el)]));
    expect(el.hasAttribute('aria-hidden')).toBe(false);
    expect(el.hasAttribute('inert')).toBe(false);
  });

  it('removes aria-hidden on deactivate', () => {
    const el = document.createElement('div');
    const { rerender } = renderHook(({ active }) => useInertWhile(active, [makeRef(el)]), {
      initialProps: { active: true },
    });
    expect(el.getAttribute('aria-hidden')).toBe('true');
    rerender({ active: false });
    expect(el.hasAttribute('aria-hidden')).toBe(false);
  });

  it('removes aria-hidden on unmount', () => {
    const el = document.createElement('div');
    const { unmount } = renderHook(() => useInertWhile(true, [makeRef(el)]));
    expect(el.getAttribute('aria-hidden')).toBe('true');
    unmount();
    expect(el.hasAttribute('aria-hidden')).toBe(false);
  });

  it('no-ops on a null ref without throwing', () => {
    expect(() => renderHook(() => useInertWhile(true, [makeRef(null)]))).not.toThrow();
  });

  it('uses the real inert attribute when the environment supports it, never both', () => {
    const el = document.createElement('div');
    // Simulate a browser that implements the `inert` IDL attribute — the
    // hook checks `'inert' in elements[0]`, so defining it on the
    // prototype is what the `in` check observes.
    const descriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'inert');
    Object.defineProperty(HTMLElement.prototype, 'inert', {
      configurable: true,
      value: false,
    });

    try {
      renderHook(() => useInertWhile(true, [makeRef(el)]));
      expect(el.hasAttribute('inert')).toBe(true);
      expect(el.hasAttribute('aria-hidden')).toBe(false);
    } finally {
      if (descriptor) {
        Object.defineProperty(HTMLElement.prototype, 'inert', descriptor);
      } else {
        delete (HTMLElement.prototype as unknown as Record<string, unknown>).inert;
      }
    }
  });
});
