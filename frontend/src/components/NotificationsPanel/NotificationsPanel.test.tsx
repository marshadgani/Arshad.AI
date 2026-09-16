import { render, screen } from '@testing-library/react';
import { vi } from 'vitest';

import { NotificationsPanel } from './NotificationsPanel';

describe('NotificationsPanel', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('does not fetch while closed', () => {
    const fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    render(<NotificationsPanel isOpen={false} onClose={vi.fn()} />);

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('fetches and renders notification rows when open', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        data: [
          { id: 'n1', severity: 'warn', title: 'Bill due in 3 days', detail: 'Electricity — ₹2,140', time: '12:00' },
        ],
      }),
    }) as unknown as typeof fetch;

    render(<NotificationsPanel isOpen onClose={vi.fn()} />);

    expect(await screen.findByText('Bill due in 3 days')).toBeInTheDocument();
    expect(screen.getByText('Electricity — ₹2,140')).toBeInTheDocument();
    expect(screen.getByText('12:00')).toBeInTheDocument();
  });

  it('renders an error state with a retry button', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Server Error',
      text: async () => 'boom',
    }) as unknown as typeof fetch;

    render(<NotificationsPanel isOpen onClose={vi.fn()} />);

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('renders an empty state when there are no notifications', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: [] }),
    }) as unknown as typeof fetch;

    render(<NotificationsPanel isOpen onClose={vi.fn()} />);

    expect(await screen.findByText('No notifications')).toBeInTheDocument();
  });

  it('caps the rendered list at 20 rows for an oversized response', async () => {
    const items = Array.from({ length: 25 }, (_, i) => ({
      id: `n${i}`,
      severity: 'info',
      title: `Notification ${i}`,
      detail: 'detail',
      time: '00:00',
    }));
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: items }),
    }) as unknown as typeof fetch;

    render(<NotificationsPanel isOpen onClose={vi.fn()} />);

    await screen.findByText('Notification 0');
    expect(screen.getAllByText(/^Notification \d+$/)).toHaveLength(20);
  });
});
