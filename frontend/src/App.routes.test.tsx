import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';

vi.mock('./auth/AuthContext', () => ({
  useAuth: () => ({
    token: 'test-token',
    user: { id: 'u1', email: 'arshad@example.com', name: 'Arshad', avatarUrl: null },
    isLoading: false,
    loginWith: vi.fn(),
    logout: vi.fn(),
    setTokenFromCallback: vi.fn(),
  }),
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// AppLayout pulls in Sidebar (useFetch('/api/v1/nav')) and TopBar, neither of
// which this test needs to exercise — it only proves that /settings and
// /activity-log resolve to the right page component inside ProtectedRoutes'
// nested <Routes>, and that the catch-all still redirects unknown paths.
vi.mock('./components/AppLayout', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Dashboard is stubbed for the same reason: the catch-all case needs to prove
// that an unknown path lands ON the Dashboard, and the real one fires its own
// unmocked widget fetches, which resolve after the assertions and produce
// act() warnings unrelated to routing.
vi.mock('./dashboard/Dashboard', () => ({
  default: () => <h1>Dashboard</h1>,
}));

import { ProtectedRoutes } from './App';

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/*" element={<ProtectedRoutes />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ProtectedRoutes wiring for FEAT-153', () => {
  it('resolves /settings to the Settings page', () => {
    renderAt('/settings');
    expect(screen.getByRole('heading', { level: 1, name: 'Settings' })).toBeInTheDocument();
  });

  it('resolves /activity-log to the ActivityLog coming-soon page', () => {
    renderAt('/activity-log');
    expect(
      screen.getByRole('heading', { level: 1, name: 'Activity log' }),
    ).toBeInTheDocument();
  });

  it('still redirects an unknown path to the Dashboard rather than a dead route', () => {
    renderAt('/no-such-page');
    // Positive assertion: the previous negative-only version passed even if
    // the catch-all rendered nothing at all.
    expect(screen.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeInTheDocument();
  });
});
