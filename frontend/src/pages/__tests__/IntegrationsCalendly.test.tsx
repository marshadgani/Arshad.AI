/**
 * Frontend tests for the Integrations page Calendly personal_apikey modal flow.
 *
 * REQ-180-006: personal_apikey items (Calendly, OpenWeatherMap) open the API-key
 * modal. Submitting posts {api_key} to POST /api/v1/integrations/connect/calendly.
 * Token is cleared after submit. project_apikey behaviour unchanged.
 *
 * Uses global.fetch stubbing via vitest (same pattern as Integrations.test.tsx).
 * Queries by role/label only; input is found by placeholder since the modal
 * input has no explicit aria-label (it is type="password" placeholder="API key").
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Integrations from '../Integrations';

// ---------------------------------------------------------------------------
// Integration catalog factories
// ---------------------------------------------------------------------------

function calendlyItem(overrides: Record<string, unknown> = {}) {
  return {
    slug: 'calendly',
    kind: 'personal_apikey',
    display_name: 'Calendly',
    category: 'Productivity',
    description: 'Scheduled meetings for trip conflict checks (read-only).',
    docs_url: 'https://developer.calendly.com/api-docs',
    icon: 'calendar',
    coming_soon: false,
    coming_soon_reason: null,
    connect_prompt: null,
    status: 'disconnected',
    last_synced_at: null,
    last_error: null,
    extra: {},
    ...overrides,
  };
}

function renderItem(overrides: Record<string, unknown> = {}) {
  return {
    slug: 'render',
    kind: 'project_apikey',
    display_name: 'Render',
    category: 'Infrastructure',
    description: 'Render deployment health.',
    docs_url: null,
    icon: 'cloud',
    coming_soon: false,
    coming_soon_reason: null,
    connect_prompt: null,
    status: 'disconnected',
    last_synced_at: null,
    last_error: null,
    extra: {},
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// fetch mock helpers
// ---------------------------------------------------------------------------

function mockFetchWith(items: unknown[], connectBody?: Record<string, unknown>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST' && String(url).includes('/connect')) {
        if (connectBody) {
          const ok = connectBody.ok !== false;
          return {
            ok,
            json: async () =>
              ok
                ? { data: { integration_id: null, redirect_url: null, ingest_token: null, ...connectBody } }
                : { error: connectBody.error ?? { code: 'invalid_key', message: 'Invalid Calendly token' } },
          } as Response;
        }
        return {
          ok: true,
          json: async () => ({ data: { integration_id: null, redirect_url: null, ingest_token: null } }),
        } as Response;
      }
      return { ok: true, json: async () => ({ data: items }) } as Response;
    }),
  );
}

function renderPage() {
  return render(
    <MemoryRouter>
      <Integrations />
    </MemoryRouter>,
  );
}

describe('Integrations page – Calendly personal_apikey modal (REQ-180-006)', () => {
  beforeEach(() => {
    window.localStorage.setItem('arshad.ai:jwt', 'test-jwt');
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it('TC-401 clicking Connect on Calendly card opens the API-key modal', async () => {
    mockFetchWith([calendlyItem()]);
    const user = userEvent.setup();
    renderPage();

    // Wait for the list to load and find the Connect button
    const connectBtn = await screen.findByRole('button', { name: /^connect$/i });
    await user.click(connectBtn);

    // Modal should appear with a password input (placeholder="API key")
    const input = await screen.findByPlaceholderText(/api key/i);
    expect(input).toBeTruthy();
  });

  it('TC-402 submitting the modal posts {api_key} to /api/v1/integrations/calendly/connect', async () => {
    mockFetchWith([calendlyItem()]);
    const user = userEvent.setup();
    renderPage();

    const connectBtn = await screen.findByRole('button', { name: /^connect$/i });
    await user.click(connectBtn);

    const input = await screen.findByPlaceholderText(/api key/i);
    await user.type(input, 'my_secret_calendly_token');

    // The submit button inside the modal is labeled "Connect"
    const buttons = screen.getAllByRole('button', { name: /^connect$/i });
    // The last "Connect" button is the modal submit (the card's button is now hidden behind modal)
    await user.click(buttons[buttons.length - 1]);

    await waitFor(() => {
      const fetchCalls = (vi.mocked(global.fetch) as ReturnType<typeof vi.fn>).mock.calls;
      const connectCall = fetchCalls.find(([url]: [string]) =>
        String(url).includes('/calendly/connect'),
      );
      expect(connectCall).toBeDefined();
      const [, options] = connectCall!;
      const body = JSON.parse((options as RequestInit).body as string);
      expect(body.api_key).toBe('my_secret_calendly_token');
    });
  });

  it('TC-403 modal input is masked (type=password)', async () => {
    mockFetchWith([calendlyItem()]);
    const user = userEvent.setup();
    renderPage();

    const connectBtn = await screen.findByRole('button', { name: /^connect$/i });
    await user.click(connectBtn);

    const input = await screen.findByPlaceholderText(/api key/i);
    expect((input as HTMLInputElement).type).toBe('password');
  });

  it('TC-404 modal input is cleared after successful submit', async () => {
    mockFetchWith([calendlyItem()]);
    const user = userEvent.setup();
    renderPage();

    const connectBtn = await screen.findByRole('button', { name: /^connect$/i });
    await user.click(connectBtn);

    const input = await screen.findByPlaceholderText(/api key/i);
    await user.type(input, 'my_secret_calendly_token');

    const buttons = screen.getAllByRole('button', { name: /^connect$/i });
    await user.click(buttons[buttons.length - 1]);

    await waitFor(() => {
      // After successful submit the modal closes, so no password input remains
      // OR the input is cleared
      const inputAfter = screen.queryByPlaceholderText(/api key/i) as HTMLInputElement | null;
      if (inputAfter) {
        expect(inputAfter.value).toBe('');
      } else {
        // Modal closed — that's the expected success path
        expect(inputAfter).toBeNull();
      }
      expect(screen.queryByText('my_secret_calendly_token')).toBeNull();
    });
  });

  it('TC-405 modal shows error message on API failure without echoing token', async () => {
    mockFetchWith([calendlyItem()], { ok: false, error: { code: 'invalid_key', message: 'Invalid Calendly token' } });
    const user = userEvent.setup();
    renderPage();

    const connectBtn = await screen.findByRole('button', { name: /^connect$/i });
    await user.click(connectBtn);

    const input = await screen.findByPlaceholderText(/api key/i);
    await user.type(input, 'bad_token_value');

    const buttons = screen.getAllByRole('button', { name: /^connect$/i });
    await user.click(buttons[buttons.length - 1]);

    await waitFor(() => {
      expect(screen.getByText(/invalid|error|failed/i)).toBeTruthy();
      expect(screen.queryByText('bad_token_value')).toBeNull();
    });
  });

  it('TC-406 project_apikey items (Render) still open their modal unchanged', async () => {
    mockFetchWith([renderItem()]);
    const user = userEvent.setup();
    renderPage();

    const connectBtn = await screen.findByRole('button', { name: /^connect$/i });
    await user.click(connectBtn);

    // The same API key modal opens for project_apikey
    const input = await screen.findByPlaceholderText(/api key/i);
    expect(input).toBeTruthy();

    await user.type(input, 'rnd_test_key');
    const buttons = screen.getAllByRole('button', { name: /^connect$/i });
    await user.click(buttons[buttons.length - 1]);

    await waitFor(() => {
      const fetchCalls = (vi.mocked(global.fetch) as ReturnType<typeof vi.fn>).mock.calls;
      const connectCall = fetchCalls.find(([url]: [string]) =>
        String(url).includes('/render/connect'),
      );
      expect(connectCall).toBeDefined();
    });
  });
});
