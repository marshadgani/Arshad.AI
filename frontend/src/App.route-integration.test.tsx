/**
 * Route integration tests for the Account section of the sidebar.
 *
 * The unit test at components/Sidebar/Sidebar.test.tsx asserts the Account
 * links carry real hrefs instead of the dead `href="#"` they used to. That
 * is necessary but not sufficient: a correct href still 404s (or, here,
 * silently redirects to `/` via the `*` route) unless App.tsx actually
 * registers the route AND the page module resolves. Those two facts live
 * outside Sidebar, so no Sidebar-scoped test can see them.
 *
 * This file therefore renders the REAL <App /> — real BrowserRouter, real
 * AuthProvider, real ProtectedRoutes, real lazy() page imports — and drives
 * it by clicking, so a regression in any one of those layers fails here.
 * Only the network is stubbed.
 *
 * Navigation always starts on /settings or /activity-log rather than '/',
 * because the eager Dashboard fans out into many widget fetches that have
 * nothing to do with routing; the sidebar is present on every protected
 * route, so click-through is exercised just as well without mounting it.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from './App';

const TOKEN_KEY = 'arshad.ai:jwt';

const AUTH_USER = {
  id: 'u1',
  email: 'arshad@example.com',
  name: 'Arshad',
};

const NAV_ITEMS = [{ to: '/', label: 'Dashboard', icon: '⌂' }];

const CHAT_SESSIONS = [
  {
    id: 'sess-1',
    title: 'Quarterly numbers',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
];

function jsonOk(data: unknown) {
  return Promise.resolve({
    ok: true,
    status: 200,
    statusText: 'OK',
    json: async () => ({ data }),
    text: async () => JSON.stringify({ data }),
  } as Response);
}

/**
 * Routes by URL rather than by call order: the App tree fires /auth/me,
 * /nav and /chat/sessions concurrently, so an order-dependent mock
 * (mockResolvedValueOnce chains) would be flaky for reasons unrelated to
 * what is under test.
 */
function mockApi() {
  global.fetch = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/api/v1/auth/me')) return jsonOk(AUTH_USER);
    if (url.includes('/api/v1/nav')) return jsonOk(NAV_ITEMS);
    if (url.includes('/api/v1/chat/sessions')) return jsonOk(CHAT_SESSIONS);
    return jsonOk({});
  }) as unknown as typeof fetch;
}

function renderAppAt(path: string) {
  window.history.pushState({}, '', path);
  return render(<App />);
}

/** The sidebar is the only <aside>; scoping to it keeps these assertions
 *  off same-named links that a page body may also render. */
function sidebar() {
  return within(document.querySelector('aside') as HTMLElement);
}

/**
 * The routed page, excluding the shell. Required, not cosmetic: the shell
 * legitimately duplicates some of the page's own affordances — TopBar has
 * its own "Sign out" button and the sidebar footer prints the user's name
 * — so an unscoped screen.getByText('Arshad') matches the chrome and would
 * pass even if the Settings page rendered nothing at all.
 */
function pageBody() {
  return within(document.querySelector('main') as HTMLElement);
}

beforeEach(() => {
  window.localStorage.setItem(TOKEN_KEY, 'test-jwt');
  mockApi();
});

afterEach(() => {
  window.localStorage.clear();
  window.history.pushState({}, '', '/');
  vi.restoreAllMocks();
});

describe('Account nav links resolve to real routes', () => {
  it('renders every Account link with its registered path and no dead href', async () => {
    renderAppAt('/settings');
    await screen.findByRole('heading', { name: /^settings$/i, level: 1 });

    const nav = sidebar();
    expect(nav.getByRole('link', { name: /integrations/i })).toHaveAttribute(
      'href',
      '/integrations',
    );
    expect(nav.getByRole('link', { name: /activity log/i })).toHaveAttribute(
      'href',
      '/activity-log',
    );
    expect(nav.getByRole('link', { name: /settings/i })).toHaveAttribute('href', '/settings');

    nav.getAllByRole('link').forEach((anchor) => {
      expect(anchor.getAttribute('href')).not.toBe('#');
    });
  });

  it('navigates to Activity Log when its sidebar link is clicked', async () => {
    const user = userEvent.setup();
    renderAppAt('/settings');
    await screen.findByRole('heading', { name: /^settings$/i, level: 1 });

    await user.click(sidebar().getByRole('link', { name: /activity log/i }));

    // The page mounted — not the `*` fallback silently redirecting to '/'.
    await screen.findByRole('heading', { name: /^activity log$/i, level: 1 });
    expect(window.location.pathname).toBe('/activity-log');
  });

  it('navigates to Settings when its sidebar link is clicked', async () => {
    const user = userEvent.setup();
    renderAppAt('/activity-log');
    await screen.findByRole('heading', { name: /^activity log$/i, level: 1 });

    await user.click(sidebar().getByRole('link', { name: /settings/i }));

    await screen.findByRole('heading', { name: /^settings$/i, level: 1 });
    expect(window.location.pathname).toBe('/settings');
  });

  it('navigates to Integrations when its sidebar link is clicked', async () => {
    const user = userEvent.setup();
    renderAppAt('/settings');
    await screen.findByRole('heading', { name: /^settings$/i, level: 1 });

    await user.click(sidebar().getByRole('link', { name: /integrations/i }));

    await waitFor(() => expect(window.location.pathname).toBe('/integrations'));
    expect(
      screen.queryByRole('heading', { name: /^settings$/i, level: 1 }),
    ).not.toBeInTheDocument();
  });
});

describe('Account routes are reachable by direct URL', () => {
  it('mounts the Settings page on a cold load of /settings', async () => {
    renderAppAt('/settings');

    await screen.findByRole('heading', { name: /^settings$/i, level: 1 });
    expect(window.location.pathname).toBe('/settings');
    // Real page content, not a placeholder that merely satisfies the route.
    expect(pageBody().getByRole('button', { name: /sign out/i })).toBeInTheDocument();
  });

  it('mounts the ActivityLog page on a cold load of /activity-log', async () => {
    renderAppAt('/activity-log');

    await screen.findByRole('heading', { name: /^activity log$/i, level: 1 });
    expect(window.location.pathname).toBe('/activity-log');
    expect(await screen.findByText('Quarterly numbers')).toBeInTheDocument();
  });

  it('still redirects a genuinely unregistered path to the dashboard', async () => {
    renderAppAt('/no-such-page');

    // Guards the inverse of this feature: proving /settings and
    // /activity-log resolve is only meaningful if the `*` fallback is what
    // an unregistered path hits.
    await waitFor(() => expect(window.location.pathname).toBe('/'));
  });
});

describe('Account routes reflect their active state', () => {
  it('marks only the current route with aria-current=page', async () => {
    renderAppAt('/settings');
    await screen.findByRole('heading', { name: /^settings$/i, level: 1 });

    const nav = sidebar();
    expect(nav.getByRole('link', { name: /settings/i })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(nav.getByRole('link', { name: /activity log/i })).not.toHaveAttribute(
      'aria-current',
    );
    // '/' passes `end`, so Dashboard must not light up on a nested route.
    expect(nav.getByRole('link', { name: /dashboard/i })).not.toHaveAttribute('aria-current');
  });

  it('moves the active marker when the route changes', async () => {
    const user = userEvent.setup();
    renderAppAt('/settings');
    await screen.findByRole('heading', { name: /^settings$/i, level: 1 });

    await user.click(sidebar().getByRole('link', { name: /activity log/i }));
    await screen.findByRole('heading', { name: /^activity log$/i, level: 1 });

    const nav = sidebar();
    expect(nav.getByRole('link', { name: /activity log/i })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(nav.getByRole('link', { name: /settings/i })).not.toHaveAttribute('aria-current');
  });
});

describe('Account pages integrate with the surrounding app', () => {
  it('renders the authenticated identity from AuthContext on /settings', async () => {
    renderAppAt('/settings');
    await screen.findByRole('heading', { name: /^settings$/i, level: 1 });

    expect(pageBody().getByText('Arshad')).toBeInTheDocument();
    expect(pageBody().getByText('arshad@example.com')).toBeInTheDocument();
  });

  it('sends an unauthenticated visit to /settings to the login page', async () => {
    window.localStorage.removeItem(TOKEN_KEY);
    renderAppAt('/settings');

    await waitFor(() => expect(window.location.pathname).toBe('/login'));
    expect(
      screen.queryByRole('heading', { name: /^settings$/i, level: 1 }),
    ).not.toBeInTheDocument();
  });
});
