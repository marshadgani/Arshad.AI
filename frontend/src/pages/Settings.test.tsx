import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';

const mockUser = { id: 'u1', email: 'arshad@example.com', name: 'Arshad', avatarUrl: null };
const logoutMock = vi.fn();

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({
    token: 'test-token',
    user: mockUser,
    isLoading: false,
    loginWith: vi.fn(),
    logout: logoutMock,
    setTokenFromCallback: vi.fn(),
  }),
}));

import Settings from './Settings';

describe('Settings page', () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    logoutMock.mockReset();
    fetchSpy = vi.spyOn(globalThis, 'fetch') as unknown as ReturnType<typeof vi.fn>;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the signed-in user\'s name and email', () => {
    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );
    expect(screen.getByText('Arshad')).toBeInTheDocument();
    expect(screen.getByText('arshad@example.com')).toBeInTheDocument();
  });

  it('calls logout exactly once when Sign out is clicked', async () => {
    logoutMock.mockResolvedValue(undefined);
    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(logoutMock).toHaveBeenCalledTimes(1);
  });

  it('disables the Sign out button while logout is pending, then re-enables it', async () => {
    let resolveLogout: () => void = () => {};
    logoutMock.mockReturnValue(
      new Promise<void>((resolve) => {
        resolveLogout = resolve;
      }),
    );
    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );
    const button = screen.getByRole('button', { name: 'Sign out' });
    fireEvent.click(button);
    expect(await screen.findByRole('button', { name: 'Signing out…' })).toBeDisabled();

    resolveLogout();
    expect(await screen.findByRole('button', { name: 'Sign out' })).not.toBeDisabled();
  });

  it('never calls fetch', () => {
    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
