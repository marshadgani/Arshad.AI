/**
 * useDashboardData — githubActivity wiring (FEAT-139).
 *
 * useDashboardData has no prior test file at all (every other widget is
 * only exercised indirectly through its card's own test file), so this
 * covers the one seam that is otherwise entirely untested: that the
 * githubActivity endpoint is requested and its useFetch result is passed
 * through unchanged. Follows the vi.mock('./useFetch') pattern already
 * established in useShopifyDashboard.test.ts / useWhoopDashboard.test.ts.
 */

import { renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../hooks/useFetch');

import { useFetch } from '../hooks/useFetch';
import { type GitHubActivityRes, useDashboardData } from './useDashboardData';

const mockUseFetch = vi.mocked(useFetch);

const emptyState = { data: null, isLoading: false, error: null, refetch: vi.fn() };

const sampleItems: GitHubActivityRes[] = [
  {
    id: 'ga-1',
    title: 'Fix deploy',
    url: 'https://github.com/owner/repo/pull/7',
    number: 7,
    repository: 'owner/repo',
    kind: 'pr',
    state: 'open',
    isDraft: false,
    author: 'arshad',
    updatedAt: '2026-09-13T09:00:00.000Z',
  },
];

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useDashboardData — githubActivity wiring', () => {
  it('requests /api/v1/dashboard/github-activity', () => {
    mockUseFetch.mockReturnValue(emptyState);

    renderHook(() => useDashboardData());

    const urls = mockUseFetch.mock.calls.map((call) => call[0]);
    expect(urls).toContain('/api/v1/dashboard/github-activity');
  });

  it('passes useFetch data through as githubActivity.data', () => {
    mockUseFetch.mockImplementation((url: string) =>
      url === '/api/v1/dashboard/github-activity'
        ? { ...emptyState, data: sampleItems }
        : emptyState,
    );

    const { result } = renderHook(() => useDashboardData());

    expect(result.current.githubActivity.data).toEqual(sampleItems);
  });

  it('passes isLoading through as githubActivity.isLoading', () => {
    mockUseFetch.mockImplementation((url: string) =>
      url === '/api/v1/dashboard/github-activity'
        ? { ...emptyState, isLoading: true, data: null }
        : emptyState,
    );

    const { result } = renderHook(() => useDashboardData());

    expect(result.current.githubActivity.isLoading).toBe(true);
  });

  it('passes error through as githubActivity.error', () => {
    const err = new Error('network failure');
    mockUseFetch.mockImplementation((url: string) =>
      url === '/api/v1/dashboard/github-activity' ? { ...emptyState, error: err } : emptyState,
    );

    const { result } = renderHook(() => useDashboardData());

    expect(result.current.githubActivity.error).toBe(err);
  });

  it('does not blow up other widgets when githubActivity errors', () => {
    mockUseFetch.mockImplementation((url: string) =>
      url === '/api/v1/dashboard/github-activity'
        ? { ...emptyState, error: new Error('boom') }
        : emptyState,
    );

    const { result } = renderHook(() => useDashboardData());

    expect(result.current.tasks.error).toBeNull();
    expect(result.current.notifications.error).toBeNull();
  });
});
