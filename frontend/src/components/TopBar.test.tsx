import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
    <AuthProvider>
      <TopBar onMenuClick={onMenuClick} isNavOpen={isNavOpen} />
    </AuthProvider>,
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
});
