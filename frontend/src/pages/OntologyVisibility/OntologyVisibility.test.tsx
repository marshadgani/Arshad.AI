import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import OntologyVisibility from './OntologyVisibility';

type Row = {
  id: string;
  entity_type: 'person' | 'project';
  external_key: string;
  visibility: 'public' | 'private';
};

const PERSON: Row = { id: 'p-1', entity_type: 'person', external_key: 'alice-gh', visibility: 'private' };
const PROJECT: Row = { id: 'r-1', entity_type: 'project', external_key: 'my-project', visibility: 'public' };

type Handlers = {
  list?: (url: URL) => Response | Promise<Response>;
  patch?: (body: { ids: string[]; visibility: string }) => Response | Promise<Response>;
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function listOf(rows: Row[], total = rows.length): Response {
  return json({ data: { entities: rows, total } });
}

/** URL/method-routed fetch mock: robust to the order and number of requests. */
function installFetch(h: Handlers) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost');
    if ((init?.method ?? 'GET').toUpperCase() === 'PATCH') {
      const body = JSON.parse(String(init?.body));
      return h.patch ? h.patch(body) : json({ data: { updated: body.ids.length, unchanged: 0 } });
    }
    return h.list ? h.list(url) : listOf([PERSON, PROJECT]);
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

const patchCalls = (fn: ReturnType<typeof installFetch>) =>
  fn.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'PATCH');

const renderPage = (props: { pageSize?: number } = {}) =>
  render(
    <MemoryRouter>
      <OntologyVisibility {...props} />
    </MemoryRouter>,
  );

beforeEach(() => vi.spyOn(console, 'error').mockImplementation(() => undefined));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('four states', () => {
  it('shows a busy loading list while the request is pending', () => {
    installFetch({ list: () => new Promise<Response>(() => undefined) });
    renderPage();
    expect(screen.getByLabelText(/loading entities/i)).toHaveAttribute('aria-busy', 'true');
  });

  it('shows an empty message pointing at the sync flow', async () => {
    installFetch({ list: () => listOf([]) });
    renderPage();
    expect(await screen.findByText(/no entities found/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /sync your vault/i })).toHaveAttribute('href', '/obsidian');
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });

  it('shows an alert with Retry on a failed request, and Retry recovers', async () => {
    let calls = 0;
    installFetch({
      list: () => (++calls === 1 ? json({ error: {} }, 500) : listOf([PERSON])),
    });
    renderPage();
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not load entities/i);
    await userEvent.click(screen.getByRole('button', { name: /retry/i }));
    expect(await screen.findByText('alice-gh')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows an alert on a network failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    renderPage();
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });

  it('renders rows with type, key, current visibility and a labelled toggle', async () => {
    installFetch({});
    renderPage();
    const alice = (await screen.findByText('alice-gh')).closest('li')!;
    expect(within(alice).getByText('person')).toBeInTheDocument();
    expect(within(alice).getByText('private')).toBeInTheDocument();
    expect(within(alice).getByRole('button', { name: 'Set alice-gh to public' })).toBeEnabled();
    const proj = screen.getByText('my-project').closest('li')!;
    expect(within(proj).getByRole('button', { name: 'Set my-project to private' })).toBeEnabled();
  });
});

describe('disclosure copy', () => {
  it('states that public means written to the vault repo on next export', async () => {
    installFetch({});
    renderPage();
    await screen.findByText('alice-gh');
    expect(screen.getByText(/written to the private vault repo marshadgani\/Arshad-Ideaverse on the next export/i)).toBeInTheDocument();
  });

  it('warns that publishing a person writes their GitHub login, only when a person is in view', async () => {
    installFetch({});
    const { unmount } = renderPage();
    expect(await screen.findByRole('note')).toHaveTextContent(/github login name/i);
    unmount();
    installFetch({ list: () => listOf([PROJECT]) });
    renderPage();
    await screen.findByText('my-project');
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });

  it('never calls an export endpoint, even after a publish', async () => {
    const fn = installFetch({});
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: 'Set alice-gh to public' }));
    await screen.findByRole('status');
    expect(fn.mock.calls.some(([u]) => String(u).includes('export'))).toBe(false);
  });
});

describe('toggle', () => {
  it('sends one PATCH with the row id and flipped visibility, then reflects it', async () => {
    const fn = installFetch({});
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: 'Set alice-gh to public' }));

    await waitFor(() => expect(patchCalls(fn)).toHaveLength(1));
    const [url, init] = patchCalls(fn)[0];
    expect(String(url)).toBe('/api/v1/ontology/entities/visibility');
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({ ids: ['p-1'], visibility: 'public' });

    const alice = screen.getByText('alice-gh').closest('li')!;
    expect(await within(alice).findByText('public')).toBeInTheDocument();
    expect(within(alice).getByRole('button', { name: 'Set alice-gh to private' })).toBeInTheDocument();
  });

  it('sends private when unpublishing a public row', async () => {
    const fn = installFetch({});
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: 'Set my-project to private' }));
    await waitFor(() => expect(patchCalls(fn)).toHaveLength(1));
    expect(JSON.parse(String((patchCalls(fn)[0][1] as RequestInit).body))).toEqual({
      ids: ['r-1'],
      visibility: 'private',
    });
  });

  it('disables only the in-flight row and shows Saving while pending', async () => {
    let release!: (r: Response) => void;
    installFetch({ patch: () => new Promise<Response>((res) => (release = res)) });
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: 'Set alice-gh to public' }));

    const alice = screen.getByText('alice-gh').closest('li')!;
    expect(within(alice).getByRole('button', { name: /set alice-gh/i })).toBeDisabled();
    expect(within(alice).getByRole('button', { name: /set alice-gh/i })).toHaveTextContent(/saving/i);
    expect(screen.getByRole('button', { name: 'Set my-project to private' })).toBeEnabled();

    release(json({ data: { updated: 1, unchanged: 0 } }));
    await waitFor(() => expect(within(alice).getByRole('button')).toBeEnabled());
  });

  it('on a server error keeps the original state, shows an alert, and no export hint', async () => {
    installFetch({ patch: () => json({ error: { code: 'x', message: 'Boom' } }, 500) });
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: 'Set alice-gh to public' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/500/);
    await waitFor(() => expect(screen.getByText('alice-gh')).toBeInTheDocument());
    const alice = screen.getByText('alice-gh').closest('li')!;
    expect(within(alice).getByText('private')).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('on 404 explains the entities are gone and reloads the list', async () => {
    let lists = 0;
    installFetch({
      list: () => (++lists === 1 ? listOf([PERSON]) : listOf([])),
      patch: () => json({ error: { code: 'entity_not_found' } }, 404),
    });
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: 'Set alice-gh to public' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/no longer exist/i);
    expect(await screen.findByText(/no entities found/i)).toBeInTheDocument();
  });

  it('shows the export command only after a successful change, and says nothing is automatic', async () => {
    installFetch({});
    renderPage();
    await screen.findByText('alice-gh');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Set alice-gh to public' }));
    const status = await screen.findByRole('status');
    expect(status).toHaveTextContent(/nothing is exported automatically/i);
    expect(status).toHaveTextContent('python scripts/obsidian_vault_export.py');
  });

  it('controls are native buttons reachable by keyboard and activated with Enter', async () => {
    const fn = installFetch({});
    renderPage();
    const btn = await screen.findByRole('button', { name: 'Set alice-gh to public' });
    expect(btn).not.toHaveAttribute('tabindex', '-1');
    btn.focus();
    await userEvent.keyboard('{Enter}');
    await waitFor(() => expect(patchCalls(fn)).toHaveLength(1));
  });
});

describe('selection and bulk actions', () => {
  it('select-all selects every row in view and bulk publish sends exactly those ids', async () => {
    const fn = installFetch({});
    renderPage();
    await screen.findByText('alice-gh');
    await userEvent.click(screen.getByRole('checkbox', { name: /select all in view/i }));
    expect(screen.getByRole('checkbox', { name: 'Select alice-gh' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Select my-project' })).toBeChecked();
    expect(screen.getByText('2 selected')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /^publish selected$/i }));
    await waitFor(() => expect(patchCalls(fn)).toHaveLength(1));
    const body = JSON.parse(String((patchCalls(fn)[0][1] as RequestInit).body));
    expect(body.visibility).toBe('public');
    expect([...body.ids].sort()).toEqual(['p-1', 'r-1']);
    await waitFor(() => expect(screen.queryByText('2 selected')).not.toBeInTheDocument());
  });

  it('unpublish selected sends private for the selected row only', async () => {
    const fn = installFetch({});
    renderPage();
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Select my-project' }));
    await userEvent.click(screen.getByRole('button', { name: /unpublish selected/i }));
    await waitFor(() => expect(patchCalls(fn)).toHaveLength(1));
    expect(JSON.parse(String((patchCalls(fn)[0][1] as RequestInit).body))).toEqual({
      ids: ['r-1'],
      visibility: 'private',
    });
  });

  it('select-all toggles back to none, and bulk buttons disappear', async () => {
    installFetch({});
    renderPage();
    await screen.findByText('alice-gh');
    const all = screen.getByRole('checkbox', { name: /select all in view/i });
    await userEvent.click(all);
    await userEvent.click(all);
    expect(screen.getByRole('checkbox', { name: 'Select alice-gh' })).not.toBeChecked();
    expect(screen.queryByRole('button', { name: /^publish selected/i })).not.toBeInTheDocument();
  });

  it('changing a filter clears the selection so hidden rows cannot be bulk-changed', async () => {
    installFetch({
      list: (url) => (url.searchParams.get('type') === 'project' ? listOf([PROJECT]) : listOf([PERSON, PROJECT])),
    });
    renderPage();
    await userEvent.click(await screen.findByRole('checkbox', { name: /select all in view/i }));
    await userEvent.selectOptions(screen.getByLabelText(/^type/i), 'project');
    await screen.findByRole('checkbox', { name: 'Select my-project' });
    expect(screen.queryByRole('checkbox', { name: 'Select alice-gh' })).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Select my-project' })).not.toBeChecked();
    expect(screen.queryByText(/selected$/)).not.toBeInTheDocument();
  });
});

describe('filters and paging', () => {
  it('sends type and visibility filters to the API and resets offset', async () => {
    const urls: URL[] = [];
    installFetch({ list: (u) => (urls.push(u), listOf([PERSON], 45)) });
    renderPage({ pageSize: 20 });
    await userEvent.click(await screen.findByRole('button', { name: /next/i }));
    await waitFor(() => expect(urls[urls.length - 1].searchParams.get('offset')).toBe('20'));

    await userEvent.selectOptions(screen.getByLabelText(/^type/i), 'person');
    await userEvent.selectOptions(screen.getByLabelText(/^visibility/i), 'private');
    await waitFor(() => {
      const last = urls[urls.length - 1];
      expect(last.searchParams.get('type')).toBe('person');
      expect(last.searchParams.get('visibility')).toBe('private');
      expect(last.searchParams.get('offset')).toBe('0');
      expect(last.searchParams.get('limit')).toBe('20');
    });
  });

  it('omits filter params when set to All', async () => {
    const urls: URL[] = [];
    installFetch({ list: (u) => (urls.push(u), listOf([PERSON])) });
    renderPage();
    await screen.findByText('alice-gh');
    expect(urls[0].searchParams.has('type')).toBe(false);
    expect(urls[0].searchParams.has('visibility')).toBe(false);
  });

  it('pager: Previous disabled on first page, Next disabled on last, range text correct', async () => {
    installFetch({ list: () => listOf([PERSON], 20) });
    renderPage({ pageSize: 20 });
    await screen.findByText('alice-gh');
    expect(screen.getByRole('button', { name: /previous/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled();
    expect(screen.getByText(/1–20 of 20/)).toBeInTheDocument();
  });

  it('paging clears the selection so rows no longer in view cannot be bulk-changed', async () => {
    installFetch({ list: () => listOf([PERSON], 2) });
    renderPage({ pageSize: 1 });
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Select alice-gh' }));
    expect(screen.getByText(/1 selected/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /next/i }));
    await screen.findByText('alice-gh');
    expect(screen.queryByText(/selected$/)).not.toBeInTheDocument();
  });
});

describe('in-flight and failure states', () => {
  it('disables the bulk buttons while a request is in flight', async () => {
    let release: (r: Response) => void = () => undefined;
    installFetch({ patch: () => new Promise<Response>((resolve) => (release = resolve)) });
    renderPage();
    await userEvent.click(await screen.findByRole('checkbox', { name: /select all in view/i }));
    await userEvent.click(screen.getByRole('button', { name: /^publish selected$/i }));
    expect(screen.getByRole('button', { name: /^publish selected$/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /unpublish selected/i })).toBeDisabled();
    release(json({ data: { updated: 2, unchanged: 0 } }));
    await waitFor(() => expect(screen.queryByText(/selected$/)).not.toBeInTheDocument());
  });

  it('hides the saved banner when a later change fails', async () => {
    let calls = 0;
    installFetch({
      patch: (b) =>
        ++calls === 1 ? json({ data: { updated: b.ids.length, unchanged: 0 } }) : json({}, 500),
    });
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: 'Set alice-gh to public' }));
    expect(await screen.findByRole('status')).toHaveTextContent(/visibility saved/i);
    await userEvent.click(screen.getByRole('button', { name: 'Set my-project to private' }));
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('shows a plain message on a 422 instead of only the status code', async () => {
    installFetch({ patch: () => json({ detail: [{ msg: 'too long' }] }, 422) });
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: 'Set alice-gh to public' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/request was not valid/i);
  });

  it('keeps the login-name warning in the always-visible help text', async () => {
    installFetch({});
    renderPage();
    await screen.findByText('alice-gh');
    await userEvent.click(screen.getByRole('button', { name: /dismiss/i }));
    expect(screen.getByText(/their GitHub login name is what gets written/i)).toBeInTheDocument();
  });
});
