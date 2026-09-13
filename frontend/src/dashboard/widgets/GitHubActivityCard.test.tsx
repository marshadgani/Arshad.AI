import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { type GitHubActivityRes } from '../useDashboardData';
import { GitHubActivityCard } from './GitHubActivityCard';

function renderCard(items: GitHubActivityRes[] | null) {
  return render(
    <MemoryRouter>
      <GitHubActivityCard items={items} />
    </MemoryRouter>,
  );
}

const baseItem: GitHubActivityRes = {
  id: '1',
  title: 'Fix the login bug',
  url: 'https://github.com/owner/repo/issues/42',
  number: 42,
  repository: 'owner/repo',
  kind: 'issue',
  state: 'open',
  isDraft: false,
  author: 'arshad',
  updatedAt: new Date().toISOString(),
};

describe('GitHubActivityCard', () => {
  it('shows the empty-state CTA with a working Chat link when items is null', () => {
    renderCard(null);

    expect(screen.getByText(/No GitHub activity synced yet/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Chat' })).toHaveAttribute('href', '/chat');
  });

  it('shows the same empty state when items is an empty array', () => {
    renderCard([]);

    expect(screen.getByText(/No GitHub activity synced yet/)).toBeInTheDocument();
  });

  it('renders a linked title when url is present', () => {
    renderCard([baseItem]);

    const link = screen.getByRole('link', { name: 'Fix the login bug' });
    expect(link).toHaveAttribute('href', baseItem.url as string);
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noreferrer');
  });

  it('renders plain text (not a link) when url is null', () => {
    renderCard([{ ...baseItem, url: null }]);

    expect(screen.queryByRole('link', { name: 'Fix the login bug' })).not.toBeInTheDocument();
    expect(screen.getByText('Fix the login bug')).toBeInTheDocument();
  });

  it('includes the state word in the meta text so colour is not the only signal', () => {
    renderCard([{ ...baseItem, state: 'merged' }]);

    expect(screen.getByText(/merged/)).toBeInTheDocument();
  });

  it('shows "draft" in the meta line when isDraft is true', () => {
    renderCard([{ ...baseItem, kind: 'pr', isDraft: true }]);

    expect(screen.getByText(/draft/)).toBeInTheDocument();
  });

  it('omits a stray separator when author is null', () => {
    renderCard([{ ...baseItem, author: null }]);

    const meta = screen.getByText(/owner\/repo #42/);
    expect(meta.textContent).not.toMatch(/·\s*$/);
  });

  it('shows a busy skeleton while loading instead of the empty state', () => {
    render(
      <MemoryRouter>
        <GitHubActivityCard items={null} isLoading />
      </MemoryRouter>,
    );

    expect(screen.queryByText(/No GitHub activity synced yet/)).not.toBeInTheDocument();
    expect(screen.getByText('Loading…')).toBeInTheDocument();
  });

  it('shows an error banner instead of silently rendering nothing', () => {
    render(
      <MemoryRouter>
        <GitHubActivityCard items={null} error={new Error('boom')} />
      </MemoryRouter>,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('boom');
  });
});
