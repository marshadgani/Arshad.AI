/**
 * Unit tests for useSyncJob hook (FEAT-144).
 *
 * IMPORTANT — this file replaces an earlier version that tested a
 * hallucinated API shape (`result.current.phase`, `result.current.start`,
 * a `useFetch` dependency, a `picked`/`timed_out` phase vocabulary, and
 * document-visibility pausing) none of which exist in
 * `frontend/src/hooks/useSyncJob.ts`. That file's assertions would have
 * failed at the very first line of every test (`result.current.phase`
 * is `undefined` because the hook returns `{ state, start, reset }`, not
 * a flat object) — i.e. the previous suite never actually exercised the
 * hook. See real consumers `pages/Integrations/useSyncRunner.ts` and
 * `pages/Obsidian/Obsidian.tsx`, both of which read `syncJob.state.phase`.
 *
 * The hook talks to the network with a raw `fetch()` call (not the
 * `useFetch` hook), so these tests mock `global.fetch` directly and use
 * vitest fake timers to drive the hook's internal `setTimeout` polling
 * loop. `getToken` is mocked so auth-header behaviour is deterministic.
 *
 * Run: npx vitest run src/hooks/__tests__/useSyncJob.test.ts
 */
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../auth/tokenStorage', () => ({
  getToken: vi.fn(() => 'test-token'),
}));

import { getToken } from '../../auth/tokenStorage';
import { isTerminalPhase, useSyncJob } from '../useSyncJob';

const STATUS_URL = '/api/v1/integrations/google_calendar/sync/status';
const JOB_ID = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890';

const FAST_POLL_MS = 3_000;
const SLOW_POLL_MS = 15_000;
const SOFT_CEILING_MS = 120_000;

function jsonResponse(data: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => ({ data }) } as Response;
}

function statusBody(status: string, extra: Partial<{ error: string | null; message: string | null; attempt: number }> = {}) {
  return { job_id: JOB_ID, status, attempt: extra.attempt ?? 0, error: extra.error ?? null, message: extra.message ?? null };
}

describe('useSyncJob', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers();
    fetchMock = vi.fn().mockResolvedValue(jsonResponse(statusBody('pending')));
    vi.stubGlobal('fetch', fetchMock);
    vi.mocked(getToken).mockReturnValue('test-token');
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  // TC-060 ────────────────────────────────────────────────────────────────
  it('TC-060: starts in idle phase; start() transitions state.phase to running', async () => {
    const { result } = renderHook(() => useSyncJob());
    expect(result.current.state.phase).toBe('idle');

    act(() => {
      result.current.start(JOB_ID, STATUS_URL);
    });
    await act(async () => { await Promise.resolve(); });

    expect(result.current.state.phase).toBe('running');
    expect(result.current.state.jobId).toBe(JOB_ID);
  });

  // TC-060b ───────────────────────────────────────────────────────────────
  it('TC-060b: start() calls the status URL with job_id and bearer auth header', async () => {
    const { result } = renderHook(() => useSyncJob());
    act(() => { result.current.start(JOB_ID, STATUS_URL); });
    await act(async () => { await Promise.resolve(); });

    expect(fetchMock).toHaveBeenCalledWith(
      `${STATUS_URL}?job_id=${JOB_ID}`,
      expect.objectContaining({ headers: { Authorization: 'Bearer test-token' } }),
    );
  });

  // TC-060c ───────────────────────────────────────────────────────────────
  it('TC-060c: no token available → request sent without an Authorization header', async () => {
    vi.mocked(getToken).mockReturnValue(null);
    const { result } = renderHook(() => useSyncJob());
    act(() => { result.current.start(JOB_ID, STATUS_URL); });
    await act(async () => { await Promise.resolve(); });

    expect(fetchMock).toHaveBeenCalledWith(
      `${STATUS_URL}?job_id=${JOB_ID}`,
      expect.objectContaining({ headers: {} }),
    );
  });

  // TC-061 ────────────────────────────────────────────────────────────────
  it('TC-061: pending/picked statuses both project to phase=running and keep polling', async () => {
    const { result } = renderHook(() => useSyncJob());
    act(() => { result.current.start(JOB_ID, STATUS_URL); });
    await act(async () => { await Promise.resolve(); });

    fetchMock.mockResolvedValue(jsonResponse(statusBody('picked')));
    await act(async () => {
      vi.advanceTimersByTime(FAST_POLL_MS);
      await Promise.resolve();
    });

    expect(result.current.state.phase).toBe('running');
    expect(isTerminalPhase(result.current.state.phase)).toBe(false);
    // still polling: a further tick should trigger another fetch call
    const callsBefore = fetchMock.mock.calls.length;
    await act(async () => {
      vi.advanceTimersByTime(FAST_POLL_MS);
      await Promise.resolve();
    });
    expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBefore);
  });

  // TC-062 ────────────────────────────────────────────────────────────────
  it('TC-062: completed status → phase=completed, message="Synced", polling stops', async () => {
    const { result } = renderHook(() => useSyncJob());
    act(() => { result.current.start(JOB_ID, STATUS_URL); });
    await act(async () => { await Promise.resolve(); });

    fetchMock.mockResolvedValue(jsonResponse(statusBody('completed')));
    await act(async () => {
      vi.advanceTimersByTime(FAST_POLL_MS);
      await Promise.resolve();
    });

    expect(result.current.state.phase).toBe('completed');
    expect(result.current.state.message).toBe('Synced');

    const callsAtCompletion = fetchMock.mock.calls.length;
    // Advance well past a further poll interval — no more requests should fire.
    await act(async () => {
      vi.advanceTimersByTime(FAST_POLL_MS * 3);
      await Promise.resolve();
    });
    expect(fetchMock.mock.calls.length).toBe(callsAtCompletion);
    expect(result.current.state.phase).toBe('completed');
  });

  // TC-063 ────────────────────────────────────────────────────────────────
  it('TC-063: failed status → phase=failed with error text in message, polling stops', async () => {
    const { result } = renderHook(() => useSyncJob());
    act(() => { result.current.start(JOB_ID, STATUS_URL); });
    await act(async () => { await Promise.resolve(); });

    fetchMock.mockResolvedValue(jsonResponse(statusBody('failed', { error: 'TokenExpiredError: token expired' })));
    await act(async () => {
      vi.advanceTimersByTime(FAST_POLL_MS);
      await Promise.resolve();
    });

    expect(result.current.state.phase).toBe('failed');
    expect(result.current.state.error).toMatch(/TokenExpiredError/);
    expect(result.current.state.message).toMatch(/TokenExpiredError/);
  });

  // TC-064 ────────────────────────────────────────────────────────────────
  it('TC-064: stalled status → phase=stalled, message references ENABLE_INPROCESS_WORKER, polling stops', async () => {
    const { result } = renderHook(() => useSyncJob());
    act(() => { result.current.start(JOB_ID, STATUS_URL); });
    await act(async () => { await Promise.resolve(); });

    fetchMock.mockResolvedValue(
      jsonResponse(statusBody('stalled', { message: 'Set ENABLE_INPROCESS_WORKER=true' })),
    );
    await act(async () => {
      vi.advanceTimersByTime(FAST_POLL_MS);
      await Promise.resolve();
    });

    expect(result.current.state.phase).toBe('stalled');
    expect(result.current.state.message).toMatch(/ENABLE_INPROCESS_WORKER/);
  });

  // TC-065 ────────────────────────────────────────────────────────────────
  it('TC-065: past the soft ceiling without a terminal status, phase stays running and the poll interval slows', async () => {
    const { result } = renderHook(() => useSyncJob());
    act(() => { result.current.start(JOB_ID, STATUS_URL); });
    await act(async () => { await Promise.resolve(); });

    fetchMock.mockResolvedValue(jsonResponse(statusBody('pending')));
    await act(async () => {
      vi.advanceTimersByTime(SOFT_CEILING_MS + FAST_POLL_MS);
      await Promise.resolve();
    });

    // Still running (no timed-out phase in this hook — it just slows down).
    expect(result.current.state.phase).toBe('running');
    expect(result.current.state.message).toMatch(/Still syncing/i);

    // From here polling should now be spaced at SLOW_POLL_MS, not FAST_POLL_MS.
    const callsBefore = fetchMock.mock.calls.length;
    await act(async () => {
      vi.advanceTimersByTime(FAST_POLL_MS); // less than SLOW_POLL_MS
      await Promise.resolve();
    });
    expect(fetchMock.mock.calls.length).toBe(callsBefore); // no new call yet

    await act(async () => {
      vi.advanceTimersByTime(SLOW_POLL_MS - FAST_POLL_MS);
      await Promise.resolve();
    });
    expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBefore);
  });

  // TC-066 ────────────────────────────────────────────────────────────────
  it('TC-066: reset() returns hook to idle and stops any in-flight polling', async () => {
    const { result } = renderHook(() => useSyncJob());
    act(() => { result.current.start(JOB_ID, STATUS_URL); });
    await act(async () => { await Promise.resolve(); });

    act(() => { result.current.reset(); });
    expect(result.current.state.phase).toBe('idle');

    const callsAtReset = fetchMock.mock.calls.length;
    await act(async () => {
      vi.advanceTimersByTime(FAST_POLL_MS * 2);
      await Promise.resolve();
    });
    expect(fetchMock.mock.calls.length).toBe(callsAtReset);
  });

  // TC-068 ────────────────────────────────────────────────────────────────
  it('TC-068: unmount mid-poll does not throw and stops further fetches', async () => {
    const { result, unmount } = renderHook(() => useSyncJob());
    act(() => { result.current.start(JOB_ID, STATUS_URL); });
    await act(async () => { await Promise.resolve(); });

    const callsAtUnmount = fetchMock.mock.calls.length;
    unmount();
    expect(() => {
      act(() => { vi.advanceTimersByTime(FAST_POLL_MS * 3); });
    }).not.toThrow();
    expect(fetchMock.mock.calls.length).toBe(callsAtUnmount);
  });

  // TC-069 ────────────────────────────────────────────────────────────────
  it('TC-069: a non-OK HTTP response mid-poll is treated as transient — state is not corrupted and polling continues', async () => {
    const { result } = renderHook(() => useSyncJob());
    act(() => { result.current.start(JOB_ID, STATUS_URL); });
    await act(async () => { await Promise.resolve(); });

    fetchMock.mockResolvedValue(jsonResponse(null, false, 500));
    await act(async () => {
      vi.advanceTimersByTime(FAST_POLL_MS);
      await Promise.resolve();
    });
    // Hook swallows the error and keeps whatever phase it had (running) —
    // it does NOT flip to 'failed' on a transport/HTTP error.
    expect(result.current.state.phase).toBe('running');

    // Recovers once the network/server is healthy again.
    fetchMock.mockResolvedValue(jsonResponse(statusBody('completed')));
    await act(async () => {
      vi.advanceTimersByTime(FAST_POLL_MS);
      await Promise.resolve();
    });
    expect(result.current.state.phase).toBe('completed');
  });

  // TC-069b ───────────────────────────────────────────────────────────────
  it('TC-069b: fetch() rejecting outright (network offline) is treated as transient, same as a non-OK response', async () => {
    const { result } = renderHook(() => useSyncJob());
    act(() => { result.current.start(JOB_ID, STATUS_URL); });
    await act(async () => { await Promise.resolve(); });

    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    await act(async () => {
      vi.advanceTimersByTime(FAST_POLL_MS);
      await Promise.resolve();
    });
    expect(result.current.state.phase).toBe('running');
  });

  // TC-070 ────────────────────────────────────────────────────────────────
  it('TC-070: job_id: null data body (row not found yet) keeps polling as running rather than throwing', async () => {
    const { result } = renderHook(() => useSyncJob());
    act(() => { result.current.start(JOB_ID, STATUS_URL); });
    await act(async () => { await Promise.resolve(); });

    fetchMock.mockResolvedValue(jsonResponse(null));
    await act(async () => {
      vi.advanceTimersByTime(FAST_POLL_MS);
      await Promise.resolve();
    });

    expect(result.current.state.phase).toBe('running');
    expect(isTerminalPhase(result.current.state.phase)).toBe(false);
  });

  // TC-071 ────────────────────────────────────────────────────────────────
  it('TC-071: an unrecognised status string does not throw and is not treated as terminal', async () => {
    const { result } = renderHook(() => useSyncJob());
    act(() => { result.current.start(JOB_ID, STATUS_URL); });
    await act(async () => { await Promise.resolve(); });

    fetchMock.mockResolvedValue(jsonResponse(statusBody('COMPLETELY_UNEXPECTED_VALUE')));
    await expect(
      act(async () => {
        vi.advanceTimersByTime(FAST_POLL_MS);
        await Promise.resolve();
      }),
    ).resolves.not.toThrow();

    expect(isTerminalPhase(result.current.state.phase)).toBe(false);
  });
});
