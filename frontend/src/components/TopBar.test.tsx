import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';

import { AuthProvider } from '../auth/AuthContext';
import { CHAT_PATH } from '../routes/paths';
import TopBar from './TopBar';

const navigateMock = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => navigateMock };
});

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
    <MemoryRouter>
      <AuthProvider>
        <TopBar onMenuClick={onMenuClick} isNavOpen={isNavOpen} />
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('TopBar', () => {
  beforeEach(() => {
    navigateMock.mockClear();
  });

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

  it('every header button has type="button"', () => {
    const { container } = renderTopBar(false);
    const buttons = container.querySelectorAll('button');
    expect(buttons.length).toBeGreaterThan(0);
    buttons.forEach((btn) => expect(btn).toHaveAttribute('type', 'button'));
  });

  it('renders no unread-dot element', () => {
    const { container } = renderTopBar(false);
    expect(container.querySelector('[class*="dot"]')).not.toBeInTheDocument();
  });

  it('gear button navigates to /settings', async () => {
    const user = userEvent.setup();
    renderTopBar(false);
    await user.click(screen.getByRole('button', { name: /settings/i }));
    expect(navigateMock).toHaveBeenCalledWith('/settings');
  });

  it('bell button toggles the notifications panel and aria-expanded', async () => {
    const user = userEvent.setup();
    renderTopBar(false);
    const bell = screen.getByRole('button', { name: /notifications/i });
    expect(bell).toHaveAttribute('aria-expanded', 'false');

    await user.click(bell);
    expect(bell).toHaveAttribute('aria-expanded', 'true');
    expect(document.getElementById('notifications-panel')).not.toHaveAttribute('hidden');

    await user.click(bell);
    expect(bell).toHaveAttribute('aria-expanded', 'false');
  });

  it('avatar button toggles the profile menu', async () => {
    const user = userEvent.setup();
    renderTopBar(false);
    const avatar = screen.getByRole('button', { name: /profile/i });

    await user.click(avatar);
    expect(avatar).toHaveAttribute('aria-expanded', 'true');
    expect(document.getElementById('profile-menu')).not.toHaveAttribute('hidden');
  });

  it('opening the profile menu closes an already-open notifications menu', async () => {
    const user = userEvent.setup();
    renderTopBar(false);
    const bell = screen.getByRole('button', { name: /notifications/i });
    const avatar = screen.getByRole('button', { name: /profile/i });

    await user.click(bell);
    expect(bell).toHaveAttribute('aria-expanded', 'true');

    await user.click(avatar);
    expect(bell).toHaveAttribute('aria-expanded', 'false');
    expect(avatar).toHaveAttribute('aria-expanded', 'true');
  });

  it('Escape closes an open menu', async () => {
    const user = userEvent.setup();
    renderTopBar(false);
    const bell = screen.getByRole('button', { name: /notifications/i });

    await user.click(bell);
    expect(bell).toHaveAttribute('aria-expanded', 'true');

    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(bell).toHaveAttribute('aria-expanded', 'false'));
  });

  it('a mousedown outside the actions area closes an open menu', async () => {
    const user = userEvent.setup();
    renderTopBar(false);
    const bell = screen.getByRole('button', { name: /notifications/i });

    await user.click(bell);
    expect(bell).toHaveAttribute('aria-expanded', 'true');

    fireEvent.mouseDown(document.body);
    await waitFor(() => expect(bell).toHaveAttribute('aria-expanded', 'false'));
  });

  it('Quick Capture submit with empty or whitespace text is a no-op', async () => {
    const { container } = renderTopBar(false);
    const form = container.querySelector('form');
    if (!form) throw new Error('capture form not found');

    fireEvent.submit(form);
    expect(navigateMock).not.toHaveBeenCalled();

    const input = screen.getByLabelText(/quick capture/i);
    await userEvent.type(input, '   ');
    fireEvent.submit(form);
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it('Quick Capture happy path navigates to /chat with the draft and clears the input', async () => {
    const user = userEvent.setup();
    const { container } = renderTopBar(false);
    const input = screen.getByLabelText(/quick capture/i) as HTMLInputElement;

    await user.type(input, 'log expense lunch');
    const form = container.querySelector('form');
    if (!form) throw new Error('capture form not found');
    fireEvent.submit(form);

    expect(navigateMock).toHaveBeenCalledWith(CHAT_PATH, {
      state: { draft: 'log expense lunch' },
    });
    expect(input.value).toBe('');
  });
});
