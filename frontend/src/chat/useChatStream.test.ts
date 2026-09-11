import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useChatStream } from './useChatStream';

vi.mock('../auth/tokenStorage', () => ({
  getToken: vi.fn(),
}));

import { getToken } from '../auth/tokenStorage';
const mockGetToken = vi.mocked(getToken);

// ---------------------------------------------------------------------------
// Stream helpers
// ---------------------------------------------------------------------------

const encoder = new TextEncoder();

function sseChunk(payload: string): Uint8Array {
  return encoder.encode(`data: ${payload}\n\n`);
}

function makeStream(...chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(chunk);
      }
      controller.close();
    },
  });
}

function mockStreamFetch(stream: ReadableStream<Uint8Array> | { getReader: () => unknown }) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: 'OK',
    body: stream,
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Precondition checks
// ---------------------------------------------------------------------------

describe('useChatStream – precondition checks', () => {
  it('returns immediately when sessionId is null without issuing a fetch', async () => {
    mockGetToken.mockReturnValue('token');
    const fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useChatStream(null));
    await act(async () => { await result.current.send('hello'); });

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.isStreaming).toBe(false);
  });

  it('sets a 401 error and does not fetch when no auth token is present', async () => {
    mockGetToken.mockReturnValue(null);
    const fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useChatStream('session-1'));
    await act(async () => { await result.current.send('hello'); });

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.error).toBe('401 Unauthorized');
  });

  it('sets an error from the HTTP status when the response is not ok', async () => {
    mockGetToken.mockReturnValue('token');
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      statusText: 'Service Unavailable',
      body: null,
    }) as unknown as typeof fetch;

    const { result } = renderHook(() => useChatStream('session-1'));
    await act(async () => { await result.current.send('hello'); });

    expect(result.current.error).toBe('503 Service Unavailable');
    expect(result.current.isStreaming).toBe(false);
  });

  it('does not set an error field when fetch throws an AbortError', async () => {
    // AbortError is the expected outcome of cancelling a stream; setting an
    // error would show a spurious failure banner to the user.
    mockGetToken.mockReturnValue('token');
    const abortErr = new DOMException('The operation was aborted.', 'AbortError');
    global.fetch = vi.fn().mockRejectedValue(abortErr) as unknown as typeof fetch;

    const { result } = renderHook(() => useChatStream('session-1'));
    await act(async () => { await result.current.send('hello'); });

    expect(result.current.error).toBeNull();
    // Note: the hook returns early on AbortError without resetting isStreaming;
    // callers that cancel via cancel() get the reset via that function's own setState.
  });
});

// ---------------------------------------------------------------------------
// SSE event handling
// ---------------------------------------------------------------------------

describe('useChatStream – SSE event handling', () => {
  it('concatenates delta events to build up assistantText', async () => {
    mockGetToken.mockReturnValue('token');
    mockStreamFetch(
      makeStream(
        sseChunk(JSON.stringify({ delta: 'Hello' })),
        sseChunk(JSON.stringify({ delta: ', world' })),
        sseChunk('[DONE]'),
      ),
    );

    const { result } = renderHook(() => useChatStream('session-1'));
    await act(async () => { await result.current.send('hi'); });

    expect(result.current.assistantText).toBe('Hello, world');
    expect(result.current.isStreaming).toBe(false);
  });

  it('sets the intent field from an intent event', async () => {
    mockGetToken.mockReturnValue('token');
    mockStreamFetch(
      makeStream(
        sseChunk(JSON.stringify({ intent: 'calendar_query' })),
        sseChunk('[DONE]'),
      ),
    );

    const { result } = renderHook(() => useChatStream('session-1'));
    await act(async () => { await result.current.send('hi'); });

    expect(result.current.intent).toBe('calendar_query');
  });

  it('adds a running tool-call record when a tool_use event arrives', async () => {
    mockGetToken.mockReturnValue('token');
    mockStreamFetch(
      makeStream(
        sseChunk(JSON.stringify({ tool_use: { id: 'tu-1', name: 'get_calendar', input: { days: 7 } } })),
        sseChunk('[DONE]'),
      ),
    );

    const { result } = renderHook(() => useChatStream('session-1'));
    await act(async () => { await result.current.send('hi'); });

    expect(result.current.toolCalls).toHaveLength(1);
    expect(result.current.toolCalls[0]).toMatchObject({
      id: 'tu-1',
      name: 'get_calendar',
      status: 'running',
    });
  });

  it('transitions the tool-call to completed when a successful tool_result arrives', async () => {
    mockGetToken.mockReturnValue('token');
    mockStreamFetch(
      makeStream(
        sseChunk(JSON.stringify({ tool_use: { id: 'tu-1', name: 'get_calendar', input: {} } })),
        sseChunk(JSON.stringify({ tool_result: { id: 'tu-1', name: 'get_calendar', output: ['event-a'], is_error: false } })),
        sseChunk('[DONE]'),
      ),
    );

    const { result } = renderHook(() => useChatStream('session-1'));
    await act(async () => { await result.current.send('hi'); });

    expect(result.current.toolCalls[0]).toMatchObject({
      id: 'tu-1',
      status: 'completed',
      output: ['event-a'],
    });
  });

  it('transitions the tool-call to error when an is_error tool_result arrives', async () => {
    mockGetToken.mockReturnValue('token');
    mockStreamFetch(
      makeStream(
        sseChunk(JSON.stringify({ tool_use: { id: 'tu-1', name: 'get_calendar', input: {} } })),
        sseChunk(JSON.stringify({ tool_result: { id: 'tu-1', name: 'get_calendar', output: 'boom', is_error: true } })),
        sseChunk('[DONE]'),
      ),
    );

    const { result } = renderHook(() => useChatStream('session-1'));
    await act(async () => { await result.current.send('hi'); });

    expect(result.current.toolCalls[0]).toMatchObject({
      id: 'tu-1',
      status: 'error',
    });
  });

  it('populates the error field and stops streaming on a backend error event', async () => {
    mockGetToken.mockReturnValue('token');
    mockStreamFetch(
      makeStream(
        sseChunk(JSON.stringify({ error: { code: 'ai_overload', message: 'Too many requests' } })),
      ),
    );

    const { result } = renderHook(() => useChatStream('session-1'));
    await act(async () => { await result.current.send('hi'); });

    expect(result.current.error).toBe('ai_overload: Too many requests');
    expect(result.current.isStreaming).toBe(false);
  });

  it('sets isStreaming to false and returns when the [DONE] terminator arrives', async () => {
    mockGetToken.mockReturnValue('token');
    mockStreamFetch(
      makeStream(
        sseChunk(JSON.stringify({ delta: 'Hi' })),
        sseChunk('[DONE]'),
      ),
    );

    const { result } = renderHook(() => useChatStream('session-1'));
    await act(async () => { await result.current.send('hi'); });

    expect(result.current.isStreaming).toBe(false);
    expect(result.current.assistantText).toBe('Hi');
  });

  it('logs a console.error for a malformed SSE chunk and continues processing subsequent events', async () => {
    /**
     * Regression guard: the bare `catch { continue }` at the JSON.parse
     * boundary previously swallowed malformed chunks with zero logging.
     * A backend bug emitting garbage in the stream was therefore invisible
     * in client-side logs. This test asserts that (a) console.error is
     * called with the bad payload, and (b) valid events after the bad chunk
     * still apply correctly.
     */
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    mockGetToken.mockReturnValue('token');
    mockStreamFetch(
      makeStream(
        sseChunk('not-valid-json{'),
        sseChunk(JSON.stringify({ delta: 'After bad chunk' })),
        sseChunk('[DONE]'),
      ),
    );

    const { result } = renderHook(() => useChatStream('session-1'));
    await act(async () => { await result.current.send('hi'); });

    expect(errorSpy).toHaveBeenCalledWith(
      '[useChatStream] malformed SSE chunk, skipping',
      expect.objectContaining({ body: 'not-valid-json{' }),
    );
    expect(result.current.assistantText).toBe('After bad chunk');
    expect(result.current.error).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Abort / cancel
// ---------------------------------------------------------------------------

describe('useChatStream – abort and cancel', () => {
  it('cancel() sets isStreaming to false when a stream is in flight', async () => {
    mockGetToken.mockReturnValue('token');

    // A reader whose read() hangs indefinitely, simulating an open connection
    const mockReader = {
      read: vi.fn((): Promise<ReadableStreamReadResult<Uint8Array>> => new Promise(() => {})),
      releaseLock: vi.fn(),
    };
    mockStreamFetch({ getReader: () => mockReader });

    const { result } = renderHook(() => useChatStream('session-1'));

    // Start the stream; don't await — it blocks on reader.read()
    act(() => { void result.current.send('hi'); });

    // isStreaming is set synchronously before the first reader.read() call
    await waitFor(() => expect(result.current.isStreaming).toBe(true));

    act(() => result.current.cancel());

    await waitFor(() => expect(result.current.isStreaming).toBe(false));
    expect(result.current.error).toBeNull();
  });

  it('switching to a different sessionId calls abort() on the in-flight controller', async () => {
    // The useEffect cleanup (sessionId dependency) must abort any open stream
    // so that session A's tokens do not bleed into session B's view. We
    // cannot observe the stream stopping in a mock environment (the mock reader
    // does not honour the abort signal), so we assert directly that abort() is
    // called when the session changes.
    mockGetToken.mockReturnValue('token');

    const abortSpy = vi.spyOn(AbortController.prototype, 'abort');
    const mockReader = {
      read: vi.fn((): Promise<ReadableStreamReadResult<Uint8Array>> => new Promise(() => {})),
      releaseLock: vi.fn(),
    };
    mockStreamFetch({ getReader: () => mockReader });

    const { result, rerender } = renderHook(
      ({ id }: { id: string }) => useChatStream(id),
      { initialProps: { id: 'session-1' } },
    );

    act(() => { void result.current.send('hi'); });
    await waitFor(() => expect(result.current.isStreaming).toBe(true));

    rerender({ id: 'session-2' });

    // The useEffect cleanup on the previous sessionId must have called abort()
    expect(abortSpy).toHaveBeenCalled();
  });
});
