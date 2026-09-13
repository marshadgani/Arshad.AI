/**
 * Login page — button wiring and the sign-in failure surface.
 *
 * loginWith throws synchronously from an event handler when the backend
 * origin is unconfigured (see auth/oauthLoginUrl.ts); nothing in React
 * catches that, so the page's own try/catch is all that stands between a
 * misconfigured deploy and a button that appears dead.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import Login from './Login';

vi.mock('../auth/AuthContext');

import { useAuth } from '../auth/AuthContext';

const mockUseAuth = vi.mocked(useAuth);

function stubAuth(loginWith: (provider: 'google' | 'github') => void) {
  mockUseAuth.mockReturnValue({
    token: null,
    user: null,
    isLoading: false,
    loginWith,
    logout: vi.fn(),
    setTokenFromCallback: vi.fn(),
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('Login', () => {
  it('starts the Google sign-in flow when the Google button is pressed', async () => {
    const loginWith = vi.fn();
    stubAuth(loginWith);
    render(<Login />);

    await userEvent.click(screen.getByRole('button', { name: /continue with google/i }));

    expect(loginWith).toHaveBeenCalledWith('google');
  });

  it('starts the GitHub sign-in flow when the GitHub button is pressed', async () => {
    const loginWith = vi.fn();
    stubAuth(loginWith);
    render(<Login />);

    await userEvent.click(screen.getByRole('button', { name: /continue with github/i }));

    expect(loginWith).toHaveBeenCalledWith('github');
  });

  it('shows the thrown reason when the backend origin is not configured', async () => {
    stubAuth(() => {
      throw new Error('VITE_API_BASE_URL must be set to the backend origin');
    });
    render(<Login />);

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /continue with google/i }));

    expect(screen.getByRole('alert')).toHaveTextContent(
      'VITE_API_BASE_URL must be set to the backend origin',
    );
  });

  it('falls back to a generic message when a non-Error is thrown', async () => {
    stubAuth(() => {
      throw 'boom';
    });
    render(<Login />);

    await userEvent.click(screen.getByRole('button', { name: /continue with github/i }));

    expect(screen.getByRole('alert')).toHaveTextContent('Unable to start sign-in.');
  });

  it('marks the clicked button busy and disables both buttons while redirecting', async () => {
    // A real loginWith never returns — it hands control to window.location —
    // so the redirecting/disabled state has to persist past the click, which
    // this no-op stub simulates.
    stubAuth(() => {});
    render(<Login />);

    const googleButton = screen.getByRole('button', { name: /continue with google/i });
    const githubButton = screen.getByRole('button', { name: /continue with github/i });

    await userEvent.click(googleButton);

    expect(googleButton).toHaveAttribute('aria-busy', 'true');
    expect(googleButton).toHaveTextContent(/redirecting/i);
    expect(githubButton).toBeDisabled();
  });
});
