/**
 * useSyncJob — the actual FEAT-144 polling state machine consumed by
 * SyncJobWatcher/Integrations.tsx to turn a DAG-backed "Sync now" click
 * into an honest processing/completed/failed/stalled verdict.
 *
 * The previously-committed frontend/src/pages/Integrations.sync.test.tsx
 * used `jest.fn()` / `jest.useFakeTimers()` in a Vitest project (no
 * `jest` global is ever defined — see frontend/src/setupTests.ts and
 * vite.config.ts, both Vitest-only, no jest shim), so that entire file
 * throws `ReferenceError: jest is not defined` and never actually ran.
 * On top of that, none of its assertions touched real code: every "TC-07x"
 * mocked `fetch` and asserted against a hand-rolled reimplementation of
 * the poll loop (e.g. TC-074 asserts a 90s cap / flat 2s interval that
 * does not match this hook's real 15-minute ceiling and 2s->5s backoff).
 * This file replaces it with tests against the real useSyncJob hook.
 */

import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useSyncJob } from './useSyncJob';

// testing-library's `waitFor` polls with real timers and hangs forever
// under `vi.useFakeTimers()`. Every assertion below instead awaits this
// microtask flush (fake timers only fake macrotasks, not promise
// microtasks) immediately after a render or a timer advance.
async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status < 400,
    status,
    json: async () => body,
  };
}

function view(overrides: Record<string, unknown> = {}) {
  return {
    job_id: 'job-1',
    status: 'pending',
    progress: 'processing',
    stalled_reason: null,
    retrying: false,
    attempt: 0,
    worker_enabled: true,
    worker_alive: true,
    error_text: null,
    requested_at: new Date().toISOString(),
    picked_at: null,
    completed_at: null,
    ...overrides,
  };
}

describe('useSyncJob', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers();
    fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('does not poll when jobId is null', () => {
    const { result } = renderHook(() => useSyncJob('google_calendar', null));

    expect(result.current).toEqual({
      job: null,
      isPolling: false,
      timedOut: false,
      error: null,
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('polls processing then stops on completed, latching the terminal view', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ data: view({ progress: 'processing' }) }))
      .mockResolvedValueOnce(jsonResponse({ data: view({ progress: 'completed', completed_at: '2024-01-01T00:00:00Z' }) }));

    const { result } = renderHook(() => useSyncJob('google_calendar', 'job-1'));
    await flush();

    expect(result.current.job?.progress).toBe('processing');
    expect(result.current.isPolling).toBe(true);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(result.current.job?.progress).toBe('completed');
    expect(result.current.isPolling).toBe(false);
    expect(result.current.timedOut).toBe(false);
    expect(result.current.error).toBeNull();

    // Terminal: no further status calls even if more time passes.
    const callsAtTerminal = fetchMock.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(fetchMock.mock.calls.length).toBe(callsAtTerminal);
  });

  it('surfaces a failed verdict with error_text and stops polling', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ data: view({ progress: 'failed', error_text: 'CalendarAPIError: rate limit exceeded' }) }),
    );

    const { result } = renderHook(() => useSyncJob('google_calendar', 'job-1'));
    await flush();

    expect(result.current.job?.progress).toBe('failed');
    expect(result.current.job?.error_text).toBe('CalendarAPIError: rate limit exceeded');
    expect(result.current.isPolling).toBe(false);
  });

  it('treats stalled as terminal (stops polling) without setting timedOut', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ data: view({ progress: 'stalled', stalled_reason: 'no_worker_running', worker_enabled: false }) }),
    );

    const { result } = renderHook(() => useSyncJob('google_calendar', 'job-1'));
    await flush();

    expect(result.current.job?.progress).toBe('stalled');
    expect(result.current.isPolling).toBe(false);
    // timedOut is reserved for the 15-minute client ceiling, not a
    // server-reported stall — callers must be able to tell these apart.
    expect(result.current.timedOut).toBe(false);
  });

  it('stops polling and surfaces an error after 3 consecutive failed polls', async () => {
    fetchMock.mockResolvedValue(jsonResponse({}, 500));

    const { result } = renderHook(() => useSyncJob('google_calendar', 'job-1'));
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(3);

    expect(result.current.error).not.toBeNull();
    expect(result.current.isPolling).toBe(false);

    // A 4th tick must not fire — polling is fully stopped once pollError is set.
    const callsAtStop = fetchMock.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fetchMock.mock.calls.length).toBe(callsAtStop);
  });

  it('a single blip does not stop polling (only 3 in a row does)', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({}, 500))
      .mockResolvedValueOnce(jsonResponse({ data: view({ progress: 'processing' }) }));

    const { result } = renderHook(() => useSyncJob('google_calendar', 'job-1'));
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(result.current.job?.progress).toBe('processing');
    expect(result.current.error).toBeNull();
    expect(result.current.isPolling).toBe(true);
  });

  it('hits the 15-minute client ceiling and sets timedOut when never terminal', async () => {
    // A fresh object per call, not mockResolvedValue's single fixed
    // reference: React bails out of a state update (and this hook's
    // ceiling-check effect never re-runs) when setData receives the exact
    // same object identity it already holds, which a real fetch/JSON.parse
    // round trip never produces.
    fetchMock.mockImplementation(async () => jsonResponse({ data: view({ progress: 'processing' }) }));

    const { result } = renderHook(() => useSyncJob('google_calendar', 'job-1'));
    await flush();
    expect(result.current.job?.progress).toBe('processing');

    // Advance in poll-sized steps rather than one huge jump: the ceiling
    // check only re-runs when a fresh poll resolves (`data` changes), and
    // the poll interval itself grows 2s->5s over time, so a single giant
    // timer jump can outrun the interval reschedule and never let the
    // 15-minute check observe an elapsed time past the ceiling.
    for (let i = 0; i < 200 && !result.current.timedOut; i++) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000);
      });
    }

    expect(result.current.timedOut).toBe(true);
    expect(result.current.isPolling).toBe(false);
    // The ceiling stops polling; it must never fabricate a 'stalled'
    // verdict itself — that classification is server-only.
    expect(result.current.job?.progress).not.toBe('stalled');
  });

  it('resets state when jobId changes (new sync started for the same slug)', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ data: view({ job_id: 'job-1', progress: 'completed' }) }),
    );

    const { result, rerender } = renderHook(
      ({ jobId }: { jobId: string | null }) => useSyncJob('google_calendar', jobId),
      { initialProps: { jobId: 'job-1' } },
    );
    await flush();

    expect(result.current.job?.progress).toBe('completed');
    expect(result.current.isPolling).toBe(false);

    fetchMock.mockResolvedValueOnce(
      jsonResponse({ data: view({ job_id: 'job-2', progress: 'processing' }) }),
    );
    rerender({ jobId: 'job-2' });
    await flush();

    expect(result.current.job?.job_id).toBe('job-2');
    expect(result.current.job?.progress).toBe('processing');
    expect(result.current.isPolling).toBe(true);
    expect(result.current.timedOut).toBe(false);
    expect(result.current.error).toBeNull();
  });
});
