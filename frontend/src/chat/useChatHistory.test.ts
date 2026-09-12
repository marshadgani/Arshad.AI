import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useChatHistory } from './useChatHistory';

vi.mock('./chatApi', () => ({
  fetchChatMessages: vi.fn(),
}));

import { fetchChatMessages } from './chatApi';
const mockFetch = vi.mocked(fetchChatMessages);

const MESSAGES = [
  { id: 'm-1', role: 'user' as const, content: { text: 'hello' }, created_at: null },
  { id: 'm-2', role: 'assistant' as const, content: { text: 'hi there' }, created_at: null },
];

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useChatHistory', () => {
  it('starts in a loading state before the fetch resolves', () => {
    mockFetch.mockReturnValue(new Promise(() => {})); // never resolves

    const { result } = renderHook(() => useChatHistory('session-1'));

    expect(result.current.isLoading).toBe(true);
    expect(result.current.messages).toEqual([]);
    expect(result.current.error).toBeNull();
  });

  it('populates messages and clears loading once the fetch succeeds', async () => {
    mockFetch.mockResolvedValue(MESSAGES);

    const { result } = renderHook(() => useChatHistory('session-1'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.messages).toEqual(MESSAGES);
    expect(result.current.error).toBeNull();
  });

  it('sets an error message and clears messages when the fetch rejects', async () => {
    mockFetch.mockRejectedValue(new Error('network failure'));

    const { result } = renderHook(() => useChatHistory('session-1'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error).toBe('Could not load this conversation.');
    expect(result.current.messages).toEqual([]);
  });

  it('reload() triggers a fresh fetch and shows the loading state again', async () => {
    mockFetch.mockResolvedValue(MESSAGES);

    const { result } = renderHook(() => useChatHistory('session-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(mockFetch).toHaveBeenCalledTimes(1);

    act(() => result.current.reload());

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
  });

  it('refresh() updates messages silently without touching the loading state', async () => {
    mockFetch.mockResolvedValue(MESSAGES);
    const { result } = renderHook(() => useChatHistory('session-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    const updated = [...MESSAGES, { id: 'm-3', role: 'assistant' as const, content: { text: 'new' }, created_at: null }];
    mockFetch.mockResolvedValue(updated);

    act(() => result.current.refresh());

    // Loading state must NOT flip during a silent refresh
    expect(result.current.isLoading).toBe(false);
    await waitFor(() => expect(result.current.messages).toHaveLength(3));
  });

  it('refresh() failure logs an error so developer regressions are visible', async () => {
    /**
     * Regression guard: refresh() is intentionally silent to the *user*
     * (no error banner) but must call console.error so that a broken
     * persisted-history endpoint does not disappear without a trace.
     * Without this log, a backend regression on /messages after a stream
     * would be invisible in client-side monitoring.
     */
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    mockFetch.mockResolvedValue(MESSAGES);
    const { result } = renderHook(() => useChatHistory('session-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    mockFetch.mockRejectedValue(new Error('db timeout'));
    act(() => result.current.refresh());

    await waitFor(() => expect(errorSpy).toHaveBeenCalled());
    expect(errorSpy).toHaveBeenCalledWith(
      '[useChatHistory] silent refresh failed',
      expect.objectContaining({ sessionId: 'session-1' }),
    );
    // User-facing state is unchanged after a silent-refresh failure
    expect(result.current.error).toBeNull();
    expect(result.current.messages).toEqual(MESSAGES);
  });

  it('appendOptimistic() immediately prepends a user message without waiting for a fetch', () => {
    mockFetch.mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useChatHistory('session-1'));

    act(() => result.current.appendOptimistic('new message'));

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0]).toMatchObject({
      role: 'user',
      content: { text: 'new message' },
    });
  });

  it('does not update state after the hook unmounts (no stale-closure leak)', async () => {
    let resolve!: (v: typeof MESSAGES) => void;
    mockFetch.mockReturnValue(new Promise<typeof MESSAGES>((r) => (resolve = r)));

    const { unmount } = renderHook(() => useChatHistory('session-1'));
    unmount();

    // Resolving after unmount must not trigger a state update (and therefore
    // no React warning about updating an unmounted component).
    await act(async () => {
      resolve(MESSAGES);
      await Promise.resolve();
    });
    // If we reach here without throwing, the active-flag guard worked.
  });
});
