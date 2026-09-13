/**
 * Login page — debounce/re-entrancy guard on the provider buttons (FEAT-142
 * W3). Queries by role, per .claude/rules/frontend.md.
 */

import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../auth/AuthContext');

import { useAuth } from '../auth/AuthContext';
import Login from './Login';

const mockUseAuth = vi.mocked(useAuth);

describe('Login', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('disables the button after first click and ignores a second click', () => {
    const loginWith = vi.fn();
    mockUseAuth.mockReturnValue({
      token: null,
      user: null,
      isLoading: false,
      loginWith,
      logout: vi.fn(),
      setTokenFromCallback: vi.fn(),
    });

    render(<Login />);
    const googleButton = screen.getByRole('button', { name: /continue with google/i });

    fireEvent.click(googleButton);
    expect(googleButton).toBeDisabled();

    fireEvent.click(googleButton);
    expect(loginWith).toHaveBeenCalledTimes(1);
    expect(loginWith).toHaveBeenCalledWith('google');
  });

  it('re-enables the button when the page is restored from bfcache (pageshow persisted)', () => {
    const loginWith = vi.fn();
    mockUseAuth.mockReturnValue({
      token: null,
      user: null,
      isLoading: false,
      loginWith,
      logout: vi.fn(),
      setTokenFromCallback: vi.fn(),
    });

    render(<Login />);
    const githubButton = screen.getByRole('button', { name: /continue with github/i });

    fireEvent.click(githubButton);
    expect(githubButton).toBeDisabled();

    const pageShowEvent = new Event('pageshow') as PageTransitionEvent & Event;
    Object.defineProperty(pageShowEvent, 'persisted', { value: true });
    act(() => {
      window.dispatchEvent(pageShowEvent);
    });

    expect(githubButton).not.toBeDisabled();
  });

  it('re-enables the button after the 10s stuck-state timeout with no pageshow event', () => {
    const loginWith = vi.fn();
    mockUseAuth.mockReturnValue({
      token: null,
      user: null,
      isLoading: false,
      loginWith,
      logout: vi.fn(),
      setTokenFromCallback: vi.fn(),
    });

    render(<Login />);
    const googleButton = screen.getByRole('button', { name: /continue with google/i });

    fireEvent.click(googleButton);
    expect(googleButton).toBeDisabled();

    act(() => {
      vi.advanceTimersByTime(10_000);
    });

    expect(googleButton).not.toBeDisabled();
  });

  it('shows an accessible error banner when the URL carries a known ?error= code, and clears it on next click', () => {
    const loginWith = vi.fn();
    mockUseAuth.mockReturnValue({
      token: null,
      user: null,
      isLoading: false,
      loginWith,
      logout: vi.fn(),
      setTokenFromCallback: vi.fn(),
    });

    window.history.replaceState(null, '', '/login?error=invalid_state');

    render(<Login />);
    expect(screen.getByRole('alert')).toHaveTextContent(/session expired/i);

    const googleButton = screen.getByRole('button', { name: /continue with google/i });
    fireEvent.click(googleButton);

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('falls back to a generic message for an unrecognised error code', () => {
    mockUseAuth.mockReturnValue({
      token: null,
      user: null,
      isLoading: false,
      loginWith: vi.fn(),
      logout: vi.fn(),
      setTokenFromCallback: vi.fn(),
    });

    window.history.replaceState(null, '', '/login?error=some_new_code');

    render(<Login />);
    expect(screen.getByRole('alert')).toHaveTextContent(/something went wrong/i);
  });
});
