import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider, useAuth } from './AuthContext';

describe('AuthContext loginWith', () => {
  let originalLocation: PropertyDescriptor | undefined;
  let hrefSetter: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    originalLocation = Object.getOwnPropertyDescriptor(window, 'location');
    hrefSetter = vi.fn();
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: {
        get href() {
          return '';
        },
        set href(value: string) {
          hrefSetter(value);
        },
      },
    });

    // Auth effect fires /api/v1/auth/me whenever a token exists; keep this
    // test isolated from that network call regardless of stored token state.
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, json: async () => ({ data: null }) }),
    );
  });

  afterEach(() => {
    if (originalLocation) {
      Object.defineProperty(window, 'location', originalLocation);
    }
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it('navigates to the absolute backend Google login URL', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://backend.test');

    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider });
    result.current.loginWith('google');

    expect(hrefSetter).toHaveBeenCalledWith('https://backend.test/api/v1/auth/google/login');
  });

  it('navigates to the absolute backend GitHub login URL', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://backend.test');

    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider });
    result.current.loginWith('github');

    expect(hrefSetter).toHaveBeenCalledWith('https://backend.test/api/v1/auth/github/login');
  });

  it(
    'falls back to the absolute local backend origin in dev (VITE_API_BASE_URL unset), ' +
      'never a relative path — pins the call site against a regression to the original bug',
    () => {
      vi.stubEnv('VITE_API_BASE_URL', '');
      vi.stubEnv('PROD', false);

      const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider });
      result.current.loginWith('google');

      expect(hrefSetter).toHaveBeenCalledWith('http://localhost:8000/api/v1/auth/google/login');
      expect(hrefSetter).not.toHaveBeenCalledWith('/api/v1/auth/google/login');
    },
  );

  it(
    'throws instead of navigating when VITE_API_BASE_URL is unset in production ' +
      '— fail-loud beats silently reproducing the cross-origin cookie bug on a misconfigured deploy',
    () => {
      vi.stubEnv('VITE_API_BASE_URL', '');
      vi.stubEnv('PROD', true);

      const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider });

      expect(() => result.current.loginWith('google')).toThrow(/VITE_API_BASE_URL/i);
      expect(hrefSetter).not.toHaveBeenCalled();
    },
  );
});
