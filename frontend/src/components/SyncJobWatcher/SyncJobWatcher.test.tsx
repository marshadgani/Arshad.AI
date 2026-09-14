/**
 * SyncJobWatcher — headless controller that Integrations.tsx mounts once
 * per in-flight DAG-backed sync job. No prior test exercised it; the
 * previously-committed Integrations.sync.test.tsx never imported it (or
 * useSyncJob, or Integrations.tsx) and used `jest.fn()` in a Vitest-only
 * project, so it threw ReferenceError on every run and covered none of
 * this wiring.
 */

import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import SyncJobWatcher from './SyncJobWatcher';

function jsonResponse(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('SyncJobWatcher', () => {
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

  it('forwards a completed poll to onUpdate and not onError', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        data: {
          job_id: 'job-1',
          status: 'completed',
          progress: 'completed',
          stalled_reason: null,
          retrying: false,
          attempt: 0,
          worker_enabled: true,
          worker_alive: true,
          error_text: null,
          requested_at: '2024-01-01T00:00:00Z',
          picked_at: '2024-01-01T00:00:05Z',
          completed_at: '2024-01-01T00:00:10Z',
        },
      }),
    );
    const onUpdate = vi.fn();
    const onError = vi.fn();

    render(
      <SyncJobWatcher slug="google_calendar" jobId="job-1" onUpdate={onUpdate} onError={onError} />,
    );
    await flush();

    expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({ progress: 'completed' }));
    expect(onError).not.toHaveBeenCalled();
  });

  it('calls onError, not onUpdate, once the status endpoint fails 3 times in a row', async () => {
    fetchMock.mockResolvedValue(jsonResponse({}, 500));
    const onUpdate = vi.fn();
    const onError = vi.fn();

    render(
      <SyncJobWatcher slug="google_calendar" jobId="job-1" onUpdate={onUpdate} onError={onError} />,
    );
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0]).toBeInstanceOf(Error);
    expect(onUpdate).not.toHaveBeenCalled();
  });

  it('renders nothing (headless)', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: null }, 404));
    const { container } = render(
      <SyncJobWatcher slug="google_calendar" jobId="job-1" onUpdate={vi.fn()} />,
    );
    await flush();
    expect(container.firstChild).toBeNull();
  });
});
