import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import Settings from './Settings';

vi.mock('../../auth/AuthContext');

import { useAuth } from '../../auth/AuthContext';

const mockUseAuth = vi.mocked(useAuth);

function stubAuth(logout: () => Promise<void>) {
  mockUseAuth.mockReturnValue({
    token: 'jwt',
    user: { id: 'u1', email: 'arshad@example.com', name: 'Arshad', avatarUrl: null },
    isLoading: false,
    loginWith: vi.fn(),
    logout,
    setTokenFromCallback: vi.fn(),
  });
}

describe('Settings', () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute('data-motion');
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the signed-in user', () => {
    stubAuth(vi.fn());
    render(<Settings />);
    expect(screen.getByText('Arshad')).toBeInTheDocument();
    expect(screen.getByText('arshad@example.com')).toBeInTheDocument();
  });

  it('signs out when the button is pressed', async () => {
    const logout = vi.fn().mockResolvedValue(undefined);
    stubAuth(logout);
    const user = userEvent.setup();
    render(<Settings />);

    await user.click(screen.getByRole('button', { name: /sign out/i }));
    expect(logout).toHaveBeenCalled();
  });

  it('toggles reduced motion and reflects it on the document root', async () => {
    stubAuth(vi.fn());
    const user = userEvent.setup();
    render(<Settings />);

    const toggle = screen.getByRole('switch', { name: /reduce motion/i });
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    expect(document.documentElement.dataset.motion).toBe('auto');

    await user.click(toggle);

    expect(toggle).toHaveAttribute('aria-checked', 'true');
    expect(document.documentElement.dataset.motion).toBe('reduced');
    expect(window.localStorage.getItem('arshad.ai:preferences')).toContain('"reducedMotion":true');
  });
});
