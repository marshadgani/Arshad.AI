/**
 * LoginRoute guard — a signed-in user redirected to /login?reason=... must not
 * be silently bounced to the dashboard (the FEAT-156 symptom).
 */

import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from './App';

vi.mock('./auth/AuthContext', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuth: vi.fn(),
}));
vi.mock('./pages/Login', () => ({ default: () => <div>login-page</div> }));
vi.mock('./pages/Integrations', () => ({ default: () => <div>integrations-page</div> }));
vi.mock('./dashboard/Dashboard', () => ({ default: () => <div>dashboard-page</div> }));
vi.mock('./components/AppLayout', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import { useAuth } from './auth/AuthContext';

function signedIn(token: string | null) {
  vi.mocked(useAuth).mockReturnValue({
    token,
    user: token ? ({ id: 'u1' } as never) : null,
    isLoading: false,
    loginWith: vi.fn(),
    loginWithPassword: vi.fn(),
    logout: vi.fn(),
    setTokenFromCallback: vi.fn(),
  });
}

describe('LoginRoute', () => {
  beforeEach(() => vi.spyOn(console, 'error').mockImplementation(() => {}));
  afterEach(() => {
    vi.restoreAllMocks();
    window.history.pushState({}, '', '/');
  });

  it('signed-in user with ?reason is sent to /integrations, preserving the reason', () => {
    signedIn('jwt');
    window.history.pushState({}, '', '/login?reason=missing_github_scope');
    render(<App />);
    expect(screen.getByText('integrations-page')).toBeInTheDocument();
    expect(window.location.pathname).toBe('/integrations');
    expect(window.location.search).toBe('?reason=missing_github_scope');
  });

  it('signed-in user without reason still goes to the dashboard', () => {
    signedIn('jwt');
    window.history.pushState({}, '', '/login');
    render(<App />);
    expect(screen.getByText('dashboard-page')).toBeInTheDocument();
  });

  it('rejects a malformed reason instead of forwarding it', () => {
    signedIn('jwt');
    window.history.pushState({}, '', '/login?reason=%3Cscript%3E&x=1');
    render(<App />);
    expect(screen.getByText('dashboard-page')).toBeInTheDocument();
    expect(window.location.search).toBe('');
  });

  it('signed-out user sees the login page', () => {
    signedIn(null);
    window.history.pushState({}, '', '/login?reason=missing_github_scope');
    render(<App />);
    expect(screen.getByText('login-page')).toBeInTheDocument();
  });
});
