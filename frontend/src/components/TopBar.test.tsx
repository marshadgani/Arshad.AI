import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { vi } from 'vitest';

import { AuthProvider } from '../auth/AuthContext';
import { CHAT_PATH } from '../routes';
import TopBar from './TopBar';

// Probe rendered at CHAT_PATH so we can assert both that navigation
// happened AND that router state (the draft) travelled with it, without
// mocking useNavigate directly.
function ChatProbe() {
  const location = useLocation();
  const draft = (location.state as { draft?: string } | null)?.draft;
  return <div data-testid="chat-probe">{draft ?? ''}</div>;
}

// The hamburger is CSS-hidden (display:none) above the mobile breakpoint —
// jsdom's default viewport is desktop-sized, so it never matches the
// accessible-name computation used by getByRole. Query by attribute
// instead; the click handler and aria wiring are what we're verifying.
function getMenuButton(container: HTMLElement): HTMLButtonElement {
  const btn = container.querySelector('[aria-label="Open navigation"]');
  if (!btn) throw new Error('menu button not found');
  return btn as HTMLButtonElement;
}

function mockFetch(authOk = false) {
  global.fetch = vi.fn().mockImplementation((url: string) => {
    if (typeof url === 'string' && url.includes('/dashboard/notifications')) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ data: [] }),
      });
    }
    return Promise.resolve(
      authOk
        ? { ok: true, status: 200, json: async () => ({ data: { id: 'u1', email: 'a@a.com', name: 'Arshad' } }) }
        : { ok: false, status: 401, json: async () => ({}) },
    );
  }) as unknown as typeof fetch;
}

function renderTopBar(isNavOpen: boolean, onMenuClick = vi.fn()) {
  mockFetch();

  return render(
    <MemoryRouter>
      <AuthProvider>
        <TopBar onMenuClick={onMenuClick} isNavOpen={isNavOpen} />
      </AuthProvider>
    </MemoryRouter>,
  );
}

function renderTopBarWithChatRoute() {
  mockFetch();

  return render(
    <MemoryRouter initialEntries={['/']}>
      <AuthProvider>
        <Routes>
          <Route
            path="/"
            element={<TopBar onMenuClick={vi.fn()} isNavOpen={false} />}
          />
          <Route path={CHAT_PATH} element={<ChatProbe />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
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

  it('opens the AccountMenu on avatar click and signs out from it', async () => {
    const user = userEvent.setup();
    renderTopBar(false);

    await user.click(screen.getByRole('button', { name: /profile/i }));
    expect(await screen.findByRole('menu')).toBeInTheDocument();

    const signOut = screen.getByRole('menuitem', { name: /sign out/i });
    expect(signOut).toBeInTheDocument();
    await user.click(signOut);
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('opens the notifications dialog on bell click and closes on Escape', async () => {
    const user = userEvent.setup();
    renderTopBar(false);

    await user.click(screen.getByRole('button', { name: /notifications/i }));
    expect(await screen.findByRole('dialog', { name: /notifications/i })).toBeInTheDocument();

    await user.keyboard('{Escape}');
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull();
    });
  });

  it('closes notifications when the account menu is opened (mutual exclusion)', async () => {
    const user = userEvent.setup();
    renderTopBar(false);

    await user.click(screen.getByRole('button', { name: /notifications/i }));
    expect(await screen.findByRole('dialog', { name: /notifications/i })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /profile/i }));
    expect(await screen.findByRole('menu')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('navigates to chat with the trimmed draft on Enter and clears the input', async () => {
    const user = userEvent.setup();
    renderTopBarWithChatRoute();

    const input = screen.getByPlaceholderText(/quick capture/i);
    await user.type(input, '  log expense{Enter}');

    const probe = await screen.findByTestId('chat-probe');
    expect(probe).toHaveTextContent('log expense');
    expect(screen.queryByPlaceholderText(/quick capture/i)).toBeNull();
  });

  it('does not navigate on whitespace-only Quick Capture input', async () => {
    const user = userEvent.setup();
    renderTopBarWithChatRoute();

    const input = screen.getByPlaceholderText(/quick capture/i);
    await user.type(input, '   {Enter}');

    expect(screen.queryByTestId('chat-probe')).toBeNull();
    expect(input).toHaveValue('   ');
  });

  it('returns focus to the bell when notifications close, instead of dropping it on <body>', async () => {
    const user = userEvent.setup();
    renderTopBar(false);

    const bell = screen.getByRole('button', { name: /notifications/i });
    await user.click(bell);
    const dialog = await screen.findByRole('dialog', { name: /notifications/i });
    await waitFor(() => expect(document.activeElement).toBe(dialog));

    await user.keyboard('{Escape}');

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull();
    });
    await waitFor(() => {
      expect(document.activeElement).toBe(bell);
    });
  });

  it('moves focus into the account menu on open and back to the avatar on close', async () => {
    const user = userEvent.setup();
    renderTopBar(false);

    const avatar = screen.getByRole('button', { name: /profile/i });
    await user.click(avatar);

    const signOut = await screen.findByRole('menuitem', { name: /sign out/i });
    await waitFor(() => expect(document.activeElement).toBe(signOut));

    await user.keyboard('{Escape}');

    await waitFor(() => {
      expect(screen.queryByRole('menu')).toBeNull();
    });
    await waitFor(() => {
      expect(document.activeElement).toBe(avatar);
    });
  });

  it('gives Quick Capture an accessible name that survives typing', async () => {
    const user = userEvent.setup();
    renderTopBar(false);

    const input = screen.getByRole('textbox', { name: /quick capture/i });
    await user.type(input, 'anything');

    expect(screen.getByRole('textbox', { name: /quick capture/i })).toBe(input);
  });

  it('focuses the Quick Capture input on Cmd+K', async () => {
    const user = userEvent.setup();
    renderTopBar(false);

    const input = screen.getByPlaceholderText(/quick capture/i);
    await user.keyboard('{Meta>}k{/Meta}');

    expect(document.activeElement).toBe(input);
  });
});
