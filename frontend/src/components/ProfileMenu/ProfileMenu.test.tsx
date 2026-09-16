import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

import { ProfileMenu } from './ProfileMenu';

const logoutMock = vi.fn();
let mockUser: { name: string | null; email: string } | null = {
  name: 'Arshad',
  email: 'arshad@example.com',
};

vi.mock('../../auth/AuthContext', () => ({
  useAuth: () => ({ user: mockUser, logout: logoutMock }),
}));

describe('ProfileMenu', () => {
  beforeEach(() => {
    logoutMock.mockClear();
  });

  it('renders the user name and email', () => {
    mockUser = { name: 'Arshad', email: 'arshad@example.com' };
    render(<ProfileMenu isOpen onClose={vi.fn()} />);

    expect(screen.getByText('Arshad')).toBeInTheDocument();
    expect(screen.getByText('arshad@example.com')).toBeInTheDocument();
  });

  it('falls back to email as the display name when name is null', () => {
    mockUser = { name: null, email: 'arshad@example.com' };
    render(<ProfileMenu isOpen onClose={vi.fn()} />);

    expect(screen.getAllByText('arshad@example.com').length).toBeGreaterThan(0);
  });

  it('calls logout when Sign out is clicked', async () => {
    mockUser = { name: 'Arshad', email: 'arshad@example.com' };
    const user = userEvent.setup();
    render(<ProfileMenu isOpen onClose={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: /sign out/i }));
    expect(logoutMock).toHaveBeenCalled();
  });

  it('is hidden when isOpen is false', () => {
    mockUser = { name: 'Arshad', email: 'arshad@example.com' };
    render(<ProfileMenu isOpen={false} onClose={vi.fn()} />);

    expect(document.getElementById('profile-menu')).toHaveAttribute('hidden');
  });
});
