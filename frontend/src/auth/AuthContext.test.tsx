/**
 * AuthContext.loginWith — pins the FEAT-142 fix: the OAuth login navigation
 * must be an ABSOLUTE backend URL when VITE_BACKEND_URL is set, and fall
 * back to the pre-existing relative path when it isn't (local dev /
 * docker-compose, where frontend and backend share one origin).
 */

import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../env');

import { backendOrigin } from '../env';
import { AuthProvider, useAuth } from './AuthContext';

const mockBackendOrigin = vi.mocked(backendOrigin);

function setLocationHref() {
  const assignments: string[] = [];
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: {
      ...window.location,
      set href(value: string) {
        assignments.push(value);
      },
      get href() {
        return assignments[assignments.length - 1] ?? '';
      },
    },
  });
  return assignments;
}

describe('AuthContext loginWith', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('navigates to an absolute backend URL when VITE_BACKEND_URL is set', () => {
    mockBackendOrigin.mockReturnValue('https://arshad-ai.onrender.com');
    const assignments = setLocationHref();

    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider });
    act(() => {
      result.current.loginWith('google');
    });

    expect(assignments).toContain(
      'https://arshad-ai.onrender.com/api/v1/auth/google/login',
    );
  });

  it('falls back to a relative path when VITE_BACKEND_URL is unset', () => {
    mockBackendOrigin.mockReturnValue('');
    const assignments = setLocationHref();

    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider });
    act(() => {
      result.current.loginWith('github');
    });

    expect(assignments).toContain('/api/v1/auth/github/login');
  });

  it('does not produce a double slash when the origin has a trailing slash stripped upstream', () => {
    mockBackendOrigin.mockReturnValue('https://arshad-ai.onrender.com');
    const assignments = setLocationHref();

    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider });
    act(() => {
      result.current.loginWith('google');
    });

    expect(assignments[assignments.length - 1]).not.toContain('//api');
  });
});
