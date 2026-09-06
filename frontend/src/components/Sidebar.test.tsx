import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { vi } from 'vitest';

import Sidebar from './Sidebar';

function mockMatchMedia(isMobile: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: isMobile,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

function mockNavFetch() {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ data: [{ to: '/', label: 'Home', icon: '⌂' }] }),
  }) as unknown as typeof fetch;
}

function renderSidebar(isOpen: boolean, onClose = vi.fn(), initialPath = '/') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="*" element={<Sidebar isOpen={isOpen} onClose={onClose} />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('Sidebar', () => {
  beforeEach(() => {
    mockNavFetch();
  });

  it('renders nav items from mocked /api/v1/nav', async () => {
    mockMatchMedia(false);
    renderSidebar(false);
    await waitFor(() => expect(screen.getByText('Home')).toBeInTheDocument());
  });

  it('has role=dialog and aria-modal when open on mobile', async () => {
    mockMatchMedia(true);
    renderSidebar(true);
    await waitFor(() => {
      const dialog = screen.getByRole('dialog', { name: /main navigation/i });
      expect(dialog).toHaveAttribute('aria-modal', 'true');
    });
  });

  it('has no dialog role on desktop', async () => {
    mockMatchMedia(false);
    renderSidebar(true);
    await waitFor(() => expect(screen.getByText('Home')).toBeInTheDocument());
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('calls onClose when the scrim is clicked', async () => {
    mockMatchMedia(true);
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderSidebar(true, onClose);
    const scrim = await screen.findByRole('button', { name: /close navigation/i });
    await user.click(scrim);
    expect(onClose).toHaveBeenCalled();
  });

  it('calls onClose on Escape when open on mobile', async () => {
    mockMatchMedia(true);
    const onClose = vi.fn();
    renderSidebar(true, onClose);
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());
    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalled();
  });

  it('does not call onClose on Escape when closed', async () => {
    mockMatchMedia(true);
    const onClose = vi.fn();
    renderSidebar(false, onClose);
    await userEvent.keyboard('{Escape}');
    expect(onClose).not.toHaveBeenCalled();
  });

  it('calls onClose when the route changes', async () => {
    mockMatchMedia(true);
    const onClose = vi.fn();

    function Harness() {
      const navigate = useNavigate();
      return (
        <>
          <button type="button" onClick={() => navigate('/other')}>go</button>
          <Sidebar isOpen onClose={onClose} />
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
    mockMatchMedia(true);
    document.body.style.overflow = 'auto';
    const { unmount } = renderSidebar(true);
    await waitFor(() => expect(document.body.style.overflow).toBe('hidden'));
    unmount();
    expect(document.body.style.overflow).toBe('auto');
  });
});
