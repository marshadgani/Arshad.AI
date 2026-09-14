import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../hooks/useFetch');

import ActivityLog from './ActivityLog';
import { useFetch } from '../../hooks/useFetch';
import type { UseFetchResult } from '../../hooks/useFetch';

const mockUseFetch = vi.mocked(useFetch);

function renderPage() {
  return render(
    <MemoryRouter>
      <ActivityLog />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ActivityLog', () => {
  it('shows a loading state while sessions are in flight', () => {
    mockUseFetch.mockReturnValue({
      data: null,
      isLoading: true,
      error: null,
      refetch: vi.fn(),
    } as UseFetchResult<unknown>);

    renderPage();
    expect(screen.getByRole('button', { name: /refreshing/i })).toBeDisabled();
  });

  it('shows an error banner with a working retry button', async () => {
    const refetch = vi.fn();
    mockUseFetch.mockReturnValue({
      data: null,
      isLoading: false,
      error: new Error('502 Bad Gateway'),
      refetch,
    } as UseFetchResult<unknown>);

    renderPage();
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('502 Bad Gateway');

    await import('@testing-library/user-event').then(({ default: userEvent }) =>
      userEvent.setup().click(screen.getByRole('button', { name: /retry/i })),
    );
    expect(refetch).toHaveBeenCalled();
  });

  it('shows an empty state with a link to start a conversation', () => {
    mockUseFetch.mockReturnValue({
      data: [],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    } as UseFetchResult<unknown>);

    renderPage();
    expect(screen.getByText('No activity yet.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /start a conversation/i })).toHaveAttribute(
      'href',
      '/chat',
    );
  });

  it('renders each session as a link to its chat transcript', () => {
    mockUseFetch.mockReturnValue({
      data: [
        {
          id: 's1',
          title: 'Q3 launch planning',
          created_at: new Date(Date.now() - 3_600_000).toISOString(),
          updated_at: new Date(Date.now() - 60_000).toISOString(),
        },
        {
          id: 's2',
          title: null,
          created_at: new Date(Date.now() - 86_400_000).toISOString(),
          updated_at: new Date(Date.now() - 86_400_000).toISOString(),
        },
      ],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    } as UseFetchResult<unknown>);

    renderPage();
    expect(screen.getByRole('link', { name: /Q3 launch planning/ })).toHaveAttribute(
      'href',
      '/chat/s1',
    );
    expect(screen.getByText('Untitled session')).toBeInTheDocument();
  });
});
