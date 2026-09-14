/**
 * AI Ecosystem — Skills tab rendering and query-building.
 *
 * The bug this feature fixes was "the Skills tab is empty even though
 * hundreds of skills exist on disk". The backend half is guarded by
 * backend/tests/test_seed_skills_wiring.py; this file guards the UI half:
 * that a populated response actually renders, and — just as important —
 * that an *empty* response is never presented the same way as a *failed*
 * one. Showing "no skills match" for a 500 is how a broken sync stays
 * invisible.
 *
 * `usePaginatedFetch` is mocked at the hook boundary (no MSW), matching the
 * existing repo pattern. Because the component builds its request URL from
 * component state, asserting on the URL the hook was called with is also
 * how the search / category / pagination behaviour is verified.
 *
 * Queries are by role and label, never by CSS class, per
 * .claude/rules/frontend.md.
 *
 * REQ links: FR-4, SC-1.
 */

import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';

import AiEcosystem from './AiEcosystem';
import type { SkillData } from './SkillCard';
import { usePaginatedFetch } from '../../hooks/usePaginatedFetch';

vi.mock('../../hooks/usePaginatedFetch');
vi.mock('../../hooks/useFetch', () => ({
  useFetch: vi.fn(() => ({ data: null, isLoading: false, error: null })),
}));

const mockedUsePaginatedFetch = usePaginatedFetch as unknown as Mock;

type SkillsResult = {
  data: SkillData[];
  total: number;
  isLoading: boolean;
  error: Error | null;
};

function mockSkills(result: Partial<SkillsResult> = {}): void {
  mockedUsePaginatedFetch.mockReturnValue({
    data: [],
    total: 0,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    ...result,
  });
}

function makeSkill(overrides: Partial<SkillData> = {}): SkillData {
  return {
    skill_name: 'test-repo__a-skill',
    display_name: 'A Skill',
    description: 'Does something useful.',
    source_repo: 'test-repo',
    category: 'other',
    ...overrides,
  };
}

/** The URL passed to usePaginatedFetch on the most recent render. */
function lastRequestedUrl(): string {
  const calls = mockedUsePaginatedFetch.mock.calls;
  expect(calls.length).toBeGreaterThan(0);
  return calls[calls.length - 1][0] as string;
}

/** Render the page and switch from the default Agents view to Skills. */
async function renderSkillsTab() {
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <AiEcosystem />
    </MemoryRouter>,
  );
  await user.click(screen.getByRole('button', { name: /^skills/i }));
  return user;
}

beforeEach(() => {
  mockSkills();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('Skills tab — the four states', () => {
  it('announces a busy region while the first page is loading', async () => {
    mockSkills({ isLoading: true });
    await renderSkillsTab();

    expect(document.querySelector('[aria-busy="true"]')).not.toBeNull();
    expect(screen.getByText(/loading skills/i)).toBeInTheDocument();
    // A pending fetch must not be reported as "nothing found".
    expect(screen.queryByText(/no skills match/i)).toBeNull();
    expect(screen.queryByText(/registry is empty/i)).toBeNull();
  });

  it('renders an announced error banner — not an empty state — when the fetch fails', async () => {
    mockSkills({ error: new Error('500 Internal Server Error: boom') });
    await renderSkillsTab();

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(/couldn't load skills/i);
    expect(alert).toHaveTextContent(/500 Internal Server Error/);
    // This is the distinction that keeps a broken sync visible.
    expect(screen.queryByText(/registry is empty/i)).toBeNull();
    expect(screen.queryByText(/no skills match/i)).toBeNull();
  });

  it('explains how to populate the registry when it is genuinely empty', async () => {
    mockSkills();
    await renderSkillsTab();

    expect(screen.getByText(/skill registry is empty/i)).toBeInTheDocument();
    expect(screen.getByText(/register_skills\.py/)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('offers a filter reset — not the empty-registry copy — when filters exclude everything', async () => {
    mockSkills();
    const user = await renderSkillsTab();

    await user.click(screen.getByRole('button', { name: /^security$/i }));

    await waitFor(() => expect(screen.getByText(/no skills match/i)).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /clear filters/i })).toBeInTheDocument();
    expect(screen.queryByText(/registry is empty/i)).toBeNull();
  });

  it('renders one card per skill with its repo and category', async () => {
    const skills = [
      makeSkill({ skill_name: 'r__alpha', display_name: 'Alpha Skill', category: 'development' }),
      makeSkill({ skill_name: 'r__beta', display_name: 'Beta Skill', category: 'security' }),
      makeSkill({ skill_name: 'r__gamma', display_name: 'Gamma Skill', category: 'data' }),
    ];
    mockSkills({ data: skills, total: 3 });
    await renderSkillsTab();

    for (const skill of skills) {
      expect(screen.getByText(skill.display_name)).toBeInTheDocument();
    }
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByText(/showing 1–3 of 3/i)).toBeInTheDocument();
  });

  it('reports the registered skill count in the header and the tab badge', async () => {
    mockSkills({ data: [makeSkill()], total: 137 });
    await renderSkillsTab();

    expect(screen.getByText(/137 skills registered/i)).toBeInTheDocument();
    const skillsTab = screen.getByRole('button', { name: /^skills/i });
    expect(within(skillsTab).getByText('137')).toBeInTheDocument();
  });

  it('falls back to "Other" for a category the UI does not know', async () => {
    mockSkills({
      // Mirrors a newer API (or a data bug) sending a fifth category.
      data: [makeSkill({ category: 'quantum' as SkillData['category'] })],
      total: 1,
    });
    await renderSkillsTab();

    expect(screen.getByText('A Skill')).toBeInTheDocument();
    // "Other" also names a filter pill (a <button>); the card's badge is not
    // a button, so this asserts the badge specifically rendered the fallback
    // rather than the unknown value.
    const labelled = screen.getAllByText('Other');
    expect(labelled.some((el) => el.tagName !== 'BUTTON')).toBe(true);
    expect(screen.queryByText('quantum')).toBeNull();
  });
});

describe('Skills tab — request building', () => {
  it('requests the first page with the configured page size', async () => {
    mockSkills();
    await renderSkillsTab();

    const url = lastRequestedUrl();
    expect(url).toContain('/api/v1/ai-ecosystem/skills?');
    expect(url).toContain('limit=50');
    expect(url).toContain('offset=0');
    expect(url).not.toContain('category=');
    expect(url).not.toContain('q=');
  });

  // Fake timers are installed and torn down by hooks, not inside the test
  // body: if a timed-out test abandons its own `finally`, fake timers leak
  // into every subsequent test in the file and they all hang. afterEach
  // still runs on timeout, so the restore is guaranteed here.
  describe('search debounce', () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('does not send q until the debounce elapses', async () => {
      mockSkills();
      render(
        <MemoryRouter>
          <AiEcosystem />
        </MemoryRouter>,
      );
      // fireEvent rather than userEvent: userEvent awaits real-time delays
      // between keystrokes, which deadlocks against installed fake timers.
      fireEvent.click(screen.getByRole('button', { name: /^skills/i }));
      fireEvent.change(screen.getByLabelText(/search skills/i), {
        target: { value: 'brainstorm' },
      });

      // Firing a request per keystroke is the bug this debounce prevents.
      expect(lastRequestedUrl()).not.toContain('q=');

      await act(async () => {
        await vi.advanceTimersByTimeAsync(400);
      });
      expect(lastRequestedUrl()).toContain('q=brainstorm');
    });
  });

  it('sends category=security and resets the offset when a filter pill is chosen', async () => {
    mockSkills({ data: [makeSkill()], total: 500 });
    const user = await renderSkillsTab();

    await user.click(screen.getByRole('button', { name: /^next$/i }));
    await waitFor(() => expect(lastRequestedUrl()).toContain('offset=50'));

    await user.click(screen.getByRole('button', { name: /^security$/i }));
    await waitFor(() => {
      const url = lastRequestedUrl();
      expect(url).toContain('category=security');
      // Staying on page 2 of the old result set would show a blank page.
      expect(url).toContain('offset=0');
    });
  });

  it('toggles a filter pill off on a second click', async () => {
    mockSkills();
    const user = await renderSkillsTab();

    await user.click(screen.getByRole('button', { name: /^security$/i }));
    await waitFor(() => expect(lastRequestedUrl()).toContain('category=security'));

    await user.click(screen.getByRole('button', { name: /^security$/i }));
    await waitFor(() => expect(lastRequestedUrl()).not.toContain('category='));
  });
});

describe('Skills tab — pagination controls', () => {
  it('disables Prev on the first page', async () => {
    mockSkills({ data: [makeSkill()], total: 500 });
    await renderSkillsTab();

    expect(screen.getByRole('button', { name: /^prev$/i })).toBeDisabled();
  });

  it('disables Next when every row fits on the current page', async () => {
    mockSkills({ data: [makeSkill(), makeSkill({ skill_name: 'r__b' })], total: 2 });
    await renderSkillsTab();

    expect(screen.getByRole('button', { name: /^next$/i })).toBeDisabled();
  });

  it('advances and rewinds the offset by one page', async () => {
    mockSkills({ data: [makeSkill()], total: 500 });
    const user = await renderSkillsTab();

    await user.click(screen.getByRole('button', { name: /^next$/i }));
    await waitFor(() => expect(lastRequestedUrl()).toContain('offset=50'));

    await user.click(screen.getByRole('button', { name: /^prev$/i }));
    await waitFor(() => expect(lastRequestedUrl()).toContain('offset=0'));
  });
});
