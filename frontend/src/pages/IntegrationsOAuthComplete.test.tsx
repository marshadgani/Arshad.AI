import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import IntegrationsOAuthComplete from './IntegrationsOAuthComplete';

function Where() {
  const loc = useLocation();
  return <div data-testid="where">{loc.pathname + loc.search}</div>;
}

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/integrations/oauth-complete" element={<IntegrationsOAuthComplete />} />
        <Route path="/integrations" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('IntegrationsOAuthComplete', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('shows a connecting status while the request is in flight', () => {
    vi.mocked(fetch).mockReturnValue(new Promise(() => {}));
    renderAt('/integrations/oauth-complete?pending=p1&slug=github');
    expect(screen.getByRole('status')).toHaveTextContent('Connecting');
  });

  it('navigates to connected on success and posts the pending key in the body', async () => {
    vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({}) } as Response);
    renderAt('/integrations/oauth-complete?pending=p1&slug=github');
    await waitFor(() =>
      expect(screen.getByTestId('where')).toHaveTextContent('/integrations?connected=github'),
    );
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe('/api/v1/integrations/oauth-complete');
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      pending_key: 'p1',
      slug: 'github',
    });
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
  });

  it('navigates with the backend error code on failure', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ error: { code: 'state_user_mismatch' } }),
    } as Response);
    renderAt('/integrations/oauth-complete?pending=p1&slug=github');
    await waitFor(() =>
      expect(screen.getByTestId('where')).toHaveTextContent(
        '/integrations?error=state_user_mismatch&slug=github',
      ),
    );
  });

  it('reports missing params without calling the API', async () => {
    renderAt('/integrations/oauth-complete');
    await waitFor(() =>
      expect(screen.getByTestId('where')).toHaveTextContent(
        '/integrations?error=missing_pending_params',
      ),
    );
    expect(fetch).not.toHaveBeenCalled();
  });

  it('navigates with internal_error when the request itself fails', async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError('network down'));
    renderAt('/integrations/oauth-complete?pending=p1&slug=github');
    await waitFor(() =>
      expect(screen.getByTestId('where')).toHaveTextContent('error=internal_error'),
    );
  });

  it('falls back to internal_error when the error body is not JSON', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => {
        throw new SyntaxError('bad json');
      },
    } as unknown as Response);
    renderAt('/integrations/oauth-complete?pending=p1&slug=github');
    await waitFor(() =>
      expect(screen.getByTestId('where')).toHaveTextContent('error=internal_error'),
    );
  });

  it('reports an expired session on a 401', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({}),
    } as Response);
    renderAt('/integrations/oauth-complete?pending=p1&slug=github');
    await waitFor(() =>
      expect(screen.getByTestId('where')).toHaveTextContent('error=session_expired'),
    );
  });

  it('sends no Authorization header when there is no stored token', async () => {
    vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({}) } as Response);
    renderAt('/integrations/oauth-complete?pending=p1&slug=github');
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled());
    const headers = (vi.mocked(fetch).mock.calls[0][1] as RequestInit).headers as Record<
      string,
      string
    >;
    expect(headers.Authorization).toBeUndefined();
  });
});
