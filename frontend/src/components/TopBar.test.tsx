import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { vi } from 'vitest';

import { AuthProvider } from '../auth/AuthContext';
import TopBar from './TopBar';

// The hamburger is CSS-hidden (display:none) above the mobile breakpoint —
// jsdom's default viewport is desktop-sized, so it never matches the
// accessible-name computation used by getByRole. Query by attribute
// instead; the click handler and aria wiring are what we're verifying.
function getMenuButton(container: HTMLElement): HTMLButtonElement {
  const btn = container.querySelector('[aria-label="Open navigation"]');
  if (!btn) throw new Error('menu button not found');
  return btn as HTMLButtonElement;
}

function renderTopBar(isNavOpen: boolean, onMenuClick = vi.fn()) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: false,
    status: 401,
    json: async () => ({}),
  }) as unknown as typeof fetch;

  return render(
    <MemoryRouter initialEntries={['/finance']}>
      <AuthProvider>
        <TopBar onMenuClick={onMenuClick} isNavOpen={isNavOpen} />
        <Routes>
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

function LocationProbe() {
  const { pathname, state } = useLocation();
  return (
    <output data-testid="location">
      {pathname}|{(state as { draft?: string } | null)?.draft ?? ''}
    </output>
  );
}

describe('TopBar', () => {
  it('calls onMenuClick when the hamburger is clicked', async () => {
    const onMenuClick = vi.fn();
    const user = userEvent.setup();
    const { container } = renderTopBar(false, onMenuClick);
    await user.click(getMenuButton(container));
    expect(onMenuClick).toHaveBeenCalled();
  });

  it('reflects isNavOpen via aria-expanded', () => {
    const { container } = renderTopBar(true);
    expect(getMenuButton(container)).toHaveAttribute('aria-expanded', 'true');
  });

  it('still renders the sign-out button', () => {
    renderTopBar(false);
    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument();
  });

  it('quick capture opens a new chat with the text prefilled, not sent', async () => {
    const user = userEvent.setup();
    renderTopBar(false);
    await user.type(screen.getByRole('textbox', { name: /quick capture/i }), 'buy milk{Enter}');
    expect(screen.getByTestId('location')).toHaveTextContent('/chat|buy milk');
    expect(screen.getByRole('textbox', { name: /quick capture/i })).toHaveValue('');
  });

  it('quick capture ignores an empty submit', async () => {
    const user = userEvent.setup();
    renderTopBar(false);
    await user.type(screen.getByRole('textbox', { name: /quick capture/i }), '   {Enter}');
    expect(screen.getByTestId('location')).toHaveTextContent('/finance|');
  });

  it('Cmd/Ctrl+K focuses quick capture', async () => {
    const user = userEvent.setup();
    renderTopBar(false);
    await user.keyboard('{Control>}k{/Control}');
    expect(screen.getByRole('textbox', { name: /quick capture/i })).toHaveFocus();
  });

  it('the bell goes to the dashboard and the gear to integrations', async () => {
    const user = userEvent.setup();
    renderTopBar(false);
    await user.click(screen.getByRole('button', { name: 'Integrations and settings' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/integrations');
    await user.click(screen.getByRole('button', { name: 'Notifications' }));
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/\|/);
  });

  it('the avatar is a label, not a button that does nothing', () => {
    renderTopBar(false);
    expect(screen.queryByRole('button', { name: /profile/i })).not.toBeInTheDocument();
  });
});
