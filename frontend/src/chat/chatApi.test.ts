import { afterEach, describe, expect, it, vi } from 'vitest';

import { MissingTokenError, createChatSession, fetchChatMessages } from './chatApi';

vi.mock('../auth/tokenStorage', () => ({
  getToken: vi.fn(),
}));

import { getToken } from '../auth/tokenStorage';
const mockGetToken = vi.mocked(getToken);

type RouteResponse = { status?: number; body?: unknown };

/**
 * Routes fetch by URL substring. Any URL with no configured route throws so
 * an unexpected request fails the test loudly rather than silently succeeding —
 * the same pattern used in useWhoopDashboard.test.ts.
 */
function mockFetch(routes: Record<string, RouteResponse>) {
  const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
    const key = Object.keys(routes).find((r) => url.includes(r));
    if (!key) throw new Error(`Unexpected fetch: ${url}`);
    const { status = 200, body } = routes[key];
    return {
      ok: status >= 200 && status < 300,
      status,
      statusText: String(status),
      json: async () => body,
    } as Response;
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('fetchChatMessages', () => {
  it('returns the data array from the API response envelope', async () => {
    mockGetToken.mockReturnValue('test-token');
    const messages = [
      { id: 'm-1', role: 'user', content: { text: 'hi' }, created_at: null },
    ];
    mockFetch({ '/messages': { body: { data: messages } } });

    const result = await fetchChatMessages('session-1');

    expect(result).toEqual(messages);
  });

  it('returns an empty array when the API responds with data: null', async () => {
    mockGetToken.mockReturnValue('test-token');
    mockFetch({ '/messages': { body: { data: null } } });

    const result = await fetchChatMessages('session-1');

    expect(result).toEqual([]);
  });

  it('throws when the response is not ok', async () => {
    mockGetToken.mockReturnValue('test-token');
    mockFetch({ '/messages': { status: 500, body: {} } });

    await expect(fetchChatMessages('session-1')).rejects.toThrow('500');
  });

  it('sends the Authorization header using the stored token', async () => {
    mockGetToken.mockReturnValue('my-jwt');
    const fetchMock = mockFetch({ '/messages': { body: { data: [] } } });

    await fetchChatMessages('session-abc');

    const [, init] = fetchMock.mock.calls[0];
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: 'Bearer my-jwt',
    });
  });
});

describe('createChatSession', () => {
  it('throws MissingTokenError immediately when no token is stored', async () => {
    mockGetToken.mockReturnValue(null);
    const fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    await expect(createChatSession()).rejects.toThrow(MissingTokenError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('returns the created session object on success', async () => {
    mockGetToken.mockReturnValue('test-token');
    mockFetch({ '/sessions': { status: 200, body: { data: { id: 'sess-99' } } } });

    const result = await createChatSession();

    expect(result).toEqual({ id: 'sess-99' });
  });

  it('throws when the response is not ok', async () => {
    mockGetToken.mockReturnValue('test-token');
    mockFetch({ '/sessions': { status: 422, body: {} } });

    await expect(createChatSession()).rejects.toThrow('422');
  });
});
