import { render, screen, waitFor } from '@testing-library/react';
import { createRef } from 'react';
import { vi } from 'vitest';

import { NotificationsPanel } from './NotificationsPanel';

function renderPanel(isOpen: boolean, onClose = vi.fn()) {
  const triggerRef = createRef<HTMLButtonElement>();
  return render(
    <>
      <button ref={triggerRef} type="button">
        Bell
      </button>
      <NotificationsPanel isOpen={isOpen} onClose={onClose} triggerRef={triggerRef} />
    </>,
  );
}

describe('NotificationsPanel', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders nothing and fires no request while closed', () => {
    global.fetch = vi.fn();
    const { container } = renderPanel(false);
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('fetches and renders notifications with severity as text, not colour-only, once opened', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        data: [
          { id: 'n1', severity: 'critical', title: 'Server down', detail: 'Retry failed', time: '09:00' },
        ],
      }),
    }) as unknown as typeof fetch;

    renderPanel(true);

    expect(await screen.findByRole('dialog', { name: /notifications/i })).toBeInTheDocument();
    expect(await screen.findByText('Server down')).toBeInTheDocument();
    expect(screen.getByText('Critical')).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it('shows an empty state when there are no notifications', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: [] }),
    }) as unknown as typeof fetch;

    renderPanel(true);

    expect(await screen.findByText('No notifications')).toBeInTheDocument();
  });

  it('shows an error state with a retry action on failure', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Server Error',
      text: async () => 'boom',
    }) as unknown as typeof fetch;

    renderPanel(true);

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
