import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createRef } from 'react';
import { vi } from 'vitest';

import { AccountMenu } from './AccountMenu';

const logout = vi.fn();

vi.mock('../../auth/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'u1', email: 'arshad@example.com', name: 'Arshad', avatarUrl: null },
    logout,
  }),
}));

function renderMenu(isOpen: boolean, onClose = vi.fn()) {
  const triggerRef = createRef<HTMLButtonElement>();
  return render(
    <>
      <button ref={triggerRef} type="button">
        Avatar
      </button>
      <AccountMenu isOpen={isOpen} onClose={onClose} triggerRef={triggerRef} />
    </>,
  );
}

describe('AccountMenu', () => {
  beforeEach(() => {
    logout.mockReset();
  });

  it('renders nothing while closed', () => {
    renderMenu(false);
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('shows the user identity and a Sign out menuitem', () => {
    renderMenu(true);
    expect(screen.getByRole('menu', { name: /account/i })).toBeInTheDocument();
    expect(screen.getByText('Arshad')).toBeInTheDocument();
    expect(screen.getByText('arshad@example.com')).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /sign out/i })).toBeInTheDocument();
  });

  it('calls logout and onClose when Sign out is clicked', async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderMenu(true, onClose);

    await user.click(screen.getByRole('menuitem', { name: /sign out/i }));

    expect(onClose).toHaveBeenCalled();
    expect(logout).toHaveBeenCalled();
  });
});
