import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

import { AuthProvider } from '../auth/AuthContext';
import TopBar from './TopBar';

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
    renderTopBar(false, onMenuClick);
    await user.click(screen.getByRole('button', { name: /open navigation/i }));
    expect(onMenuClick).toHaveBeenCalled();
  });

  it('reflects isNavOpen via aria-expanded', () => {
    renderTopBar(true);
    expect(screen.getByRole('button', { name: /open navigation/i })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
  });

  it('still renders the sign-out button', () => {
    renderTopBar(false);
    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument();
  });
});
