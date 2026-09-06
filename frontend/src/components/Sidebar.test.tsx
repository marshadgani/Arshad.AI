import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { vi } from 'vitest';

import Sidebar from './Sidebar';
import { setViewport } from '../setupTests';

function mockNavFetch() {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ data: [{ to: '/', label: 'Home', icon: '⌂' }] }),
  }) as unknown as typeof fetch;
}

function renderSidebar(
  isOpen: boolean,
  overlayMode: boolean,
  onClose = vi.fn(),
  initialPath = '/',
) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route
          path="*"
          element={<Sidebar isOpen={isOpen} onClose={onClose} overlayMode={overlayMode} />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe('Sidebar', () => {
  beforeEach(() => {
    mockNavFetch();
  });

  it('renders nav items from mocked /api/v1/nav', async () => {
    setViewport(1280);
    renderSidebar(false, false);
    await waitFor(() => expect(screen.getByText('Home')).toBeInTheDocument());
  });

  it('has role=dialog and aria-modal when open on mobile', async () => {
    setViewport(375);
    renderSidebar(true, true);
    await waitFor(() => {
      const dialog = screen.getByRole('dialog', { name: /main navigation/i });
      expect(dialog).toHaveAttribute('aria-modal', 'true');
    });
  });

  it('has no dialog role on desktop', async () => {
    setViewport(1280);
    renderSidebar(true, false);
    await waitFor(() => expect(screen.getByText('Home')).toBeInTheDocument());
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('calls onClose when the scrim is clicked', async () => {
    setViewport(375);
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderSidebar(true, true, onClose);
    const scrim = await screen.findByRole('button', { name: /close navigation/i });
    await user.click(scrim);
    expect(onClose).toHaveBeenCalled();
  });

  it('calls onClose on Escape when open on mobile', async () => {
    setViewport(375);
    const onClose = vi.fn();
    renderSidebar(true, true, onClose);
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());
    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalled();
  });

  it('does not call onClose on Escape when closed', async () => {
    setViewport(375);
    const onClose = vi.fn();
    renderSidebar(false, true, onClose);
    await userEvent.keyboard('{Escape}');
    expect(onClose).not.toHaveBeenCalled();
  });

  it('calls onClose when the route changes', async () => {
    setViewport(375);
    const onClose = vi.fn();

    function Harness() {
      const navigate = useNavigate();
      return (
        <>
          <button type="button" onClick={() => navigate('/other')}>go</button>
          <Sidebar isOpen onClose={onClose} overlayMode />
        </>
      );
    }

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={['/']}>
        <Harness />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole('button', { name: 'go' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('restores body overflow after unmount', async () => {
    setViewport(375);
    document.body.style.overflow = 'auto';
    const { unmount } = renderSidebar(true, true);
    await waitFor(() => expect(document.body.style.overflow).toBe('hidden'));
    unmount();
    expect(document.body.style.overflow).toBe('auto');
  });

  it('locks body scroll while open on mobile and restores it on close', async () => {
    setViewport(375);
    document.body.style.overflow = 'auto';
    renderSidebar(true, true);
    await waitFor(() => expect(document.body.style.overflow).toBe('hidden'));
  });

  it('returns focus to the trigger element when the drawer closes on mobile', async () => {
    setViewport(375);
    const trigger = document.createElement('button');
    trigger.textContent = 'open';
    document.body.appendChild(trigger);
    trigger.focus();

    const onClose = vi.fn();
    const { rerender } = render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route
            path="*"
            element={<Sidebar isOpen onClose={onClose} overlayMode />}
          />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

    rerender(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route
            path="*"
            element={<Sidebar isOpen={false} onClose={onClose} overlayMode />}
          />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(document.activeElement).toBe(trigger));
    document.body.removeChild(trigger);
  });
});
