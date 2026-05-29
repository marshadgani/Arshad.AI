import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { AuthProvider, useAuth } from './AuthContext';

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch);
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function TestConsumer() {
  const { user, isLoading, token } = useAuth();
  if (isLoading) return <div>loading</div>;
  return (
    <div>
      <span data-testid="user">{user ? user.email : 'none'}</span>
      <span data-testid="token">{token ?? 'none'}</span>
    </div>
  );
}

describe('AuthProvider', () => {
  it('renders children and shows no user when not logged in', async () => {
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    // Without a stored token, isLoading starts false → no fetch
    await waitFor(() => expect(screen.queryByText('loading')).toBeNull());
    expect(screen.getByTestId('user').textContent).toBe('none');
    expect(screen.getByTestId('token').textContent).toBe('none');
  });

  it('fetches user from /api/v1/auth/me when a stored token is present', async () => {
    localStorage.setItem('arshad.ai:jwt', 'test-jwt');

    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        data: { id: '1', email: 'arshad@example.com', name: 'Arshad', avatarUrl: null },
      }),
    });

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.queryByText('loading')).toBeNull());

    expect(screen.getByTestId('user').textContent).toBe('arshad@example.com');
    expect(screen.getByTestId('token').textContent).toBe('test-jwt');
  });

  it('clears the token and user when /api/v1/auth/me returns 401', async () => {
    localStorage.setItem('arshad.ai:jwt', 'expired-jwt');

    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
    });

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.queryByText('loading')).toBeNull());

    expect(screen.getByTestId('user').textContent).toBe('none');
    expect(screen.getByTestId('token').textContent).toBe('none');
    expect(localStorage.getItem('arshad.ai:jwt')).toBeNull();
  });

  it('throws when useAuth is used outside AuthProvider', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<TestConsumer />)).toThrow(
      'useAuth must be used within an AuthProvider',
    );
    spy.mockRestore();
  });
});
