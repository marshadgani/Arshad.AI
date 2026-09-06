import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';

import { AuthProvider } from '../auth/AuthContext';
import AppLayout from './AppLayout';
import styles from './AppLayout.module.css';
import { setViewport } from '../setupTests';

function renderAt(path: string) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: false,
    status: 401,
    json: async () => ({}),
  }) as unknown as typeof fetch;

  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          <Route
            path="*"
            element={
              <AppLayout>
                <div data-testid="route-content">content</div>
              </AppLayout>
            }
          />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('AppLayout', () => {
  it('renders no ChatBar composer on a non-chat route (regression)', () => {
    setViewport(1280);
    renderAt('/');
    expect(screen.queryByPlaceholderText(/ask arshad\.ai/i)).not.toBeInTheDocument();
  });

  it('reserves FAB padding on a non-chat route', () => {
    setViewport(1280);
    renderAt('/');
    expect(screen.getByTestId('route-content').parentElement).toHaveClass(styles.contentFabPad);
  });

  it('does not reserve FAB padding on /chat', () => {
    setViewport(1280);
    renderAt('/chat/abc');
    expect(screen.getByTestId('route-content').parentElement).not.toHaveClass(styles.contentFabPad);
  });

  it('threads overlayMode to Sidebar: dialog semantics appear at mobile widths only', async () => {
    setViewport(375);
    renderAt('/');
    const user = userEvent.setup();
    await user.click(screen.getByLabelText(/open navigation/i));
    expect(await screen.findByRole('dialog', { name: /main navigation/i })).toBeInTheDocument();

    setViewport(1280);
    renderAt('/');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('closes the nav drawer on a mobile-to-desktop rotation and restores the FAB', async () => {
    setViewport(375);
    renderAt('/');
    const user = userEvent.setup();

    await user.click(screen.getByLabelText(/open navigation/i));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /open arshad\.ai chat/i })).not.toBeInTheDocument();

    act(() => setViewport(1024));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(await screen.findByRole('link', { name: /open arshad\.ai chat/i })).toBeInTheDocument();
  });

  // Background inertness is applied either via the real `inert` attribute
  // or, in environments that don't implement it (this repo's pinned
  // jsdom), via an aria-hidden fallback (see useInertWhile). Never both.
  function isInert(el: Element | null): boolean {
    if (!el) return false;
    return el.hasAttribute('inert') || el.getAttribute('aria-hidden') === 'true';
  }

  it('makes <main> inert while the drawer is a modal, but never the hamburger or TopBar', async () => {
    setViewport(375);
    renderAt('/');
    const user = userEvent.setup();

    const main = screen.getByTestId('route-content').closest('main');
    const hamburger = screen.getByLabelText(/open navigation/i);

    expect(isInert(main)).toBe(false);

    await user.click(hamburger);
    await screen.findByRole('dialog');

    expect(isInert(main)).toBe(true);
    expect(isInert(hamburger)).toBe(false);
    expect(isInert(hamburger.closest('header'))).toBe(false);

    await user.click(screen.getByRole('button', { name: /close navigation/i }));
    expect(isInert(main)).toBe(false);
  });
});
