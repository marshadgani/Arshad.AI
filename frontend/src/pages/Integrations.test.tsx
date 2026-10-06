import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import Integrations from './Integrations';

const ITEM = {
  slug: 'github',
  kind: 'personal_oauth',
  display_name: 'GitHub',
  category: 'Code',
  description: 'Repos',
  docs_url: null,
  icon: 'github',
  coming_soon: false,
  coming_soon_reason: null,
  connect_prompt: null,
  status: 'disconnected',
  last_synced_at: null,
  last_error: null,
  extra: {},
};

type ConnectResponse = {
  integration_id: string | null;
  redirect_url: string | null;
  ingest_token: string | null;
};

function mockFetch(connectBody?: ConnectResponse) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST' && url.endsWith('/connect')) {
        return { ok: true, json: async () => ({ data: connectBody }) } as Response;
      }
      return { ok: true, json: async () => ({ data: [ITEM] }) } as Response;
    }),
  );
}

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Integrations />
    </MemoryRouter>,
  );
}

describe('Integrations return-from-provider handling', () => {
  beforeEach(() => {
    window.localStorage.setItem('arshad.ai:jwt', 'jwt');
    mockFetch();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it('shows a success message for ?connected=github', async () => {
    renderAt('/integrations?connected=github');
    expect(await screen.findByText('GitHub connected successfully')).toBeInTheDocument();
  });

  it('shows a readable error for ?error=state_user_mismatch', async () => {
    renderAt('/integrations?error=state_user_mismatch&slug=github');
    expect(await screen.findByText(/Security check failed/)).toBeInTheDocument();
  });

  it('falls back to the raw code for unknown errors', async () => {
    renderAt('/integrations?error=weird_code');
    expect(await screen.findByText(/weird_code/)).toBeInTheDocument();
  });

  it('Connect follows the returned authorize URL', async () => {
    mockFetch({
      integration_id: null,
      redirect_url: 'https://github.com/login/oauth/authorize?state=s',
      ingest_token: null,
    });
    const loc = { href: 'http://localhost/integrations' };
    vi.stubGlobal('location', loc);
    renderAt('/integrations');
    await userEvent.click(await screen.findByRole('button', { name: /connect/i }));
    await waitFor(() =>
      expect(loc.href).toBe('https://github.com/login/oauth/authorize?state=s'),
    );
  });
  it('Connect failure shows a message and does not navigate', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (init?.method === 'POST' && url.endsWith('/connect')) {
          return {
            ok: false,
            status: 400,
            json: async () => ({ error: { code: 'x', message: 'GitHub OAuth is misconfigured.' } }),
          } as Response;
        }
        return { ok: true, json: async () => ({ data: [ITEM] }) } as Response;
      }),
    );
    const loc = { href: 'http://localhost/integrations' };
    vi.stubGlobal('location', loc);
    renderAt('/integrations');
    await userEvent.click(await screen.findByRole('button', { name: /connect/i }));
    expect(await screen.findByText(/Connect failed/)).toBeInTheDocument();
    expect(loc.href).toBe('http://localhost/integrations');
  });

  it('shows a message for a forwarded ?reason', async () => {
    renderAt('/integrations?reason=missing_github_scope');
    expect(await screen.findByText(/Connect GitHub to continue/)).toBeInTheDocument();
  });
});
