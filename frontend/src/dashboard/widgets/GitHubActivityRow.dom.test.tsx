/**
 * GitHubActivityRow — DOM-level rendering (FEAT-139).
 *
 * GitHubActivityRow.test.ts already pins activityMetaLine's string
 * contract without a render. This file covers the visual assertions that
 * only show up once the component actually renders: the per-state badge
 * colour class on the status pin, and the linked-vs-plain title split.
 * These were previously untested at the DOM level — GitHubActivityCard's
 * tests only assert on visible text, never on which CSS class the pin
 * receives for a given state.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import styles from '../Dashboard.module.css';
import { type GitHubActivityRes } from '../useDashboardData';
import { GitHubActivityRow } from './GitHubActivityRow';

const baseItem: GitHubActivityRes = {
  id: 'row-1',
  title: 'Open issue title',
  url: 'https://github.com/owner/repo/issues/1',
  number: 1,
  repository: 'owner/repo',
  kind: 'issue',
  state: 'open',
  isDraft: false,
  author: 'arshad',
  updatedAt: '2026-09-10T08:00:00.000Z',
};

function renderRow(item: GitHubActivityRes) {
  return render(<GitHubActivityRow item={item} />);
}

describe('GitHubActivityRow — status pin colour per state', () => {
  it('open state gets sevInfo, not sevOk or sevWarn', () => {
    const { container } = renderRow({ ...baseItem, state: 'open' });
    const pin = container.querySelector(`.${styles.notifPin}`);

    expect(pin?.classList.contains(styles.sevInfo)).toBe(true);
    expect(pin?.classList.contains(styles.sevOk)).toBe(false);
    expect(pin?.classList.contains(styles.sevWarn)).toBe(false);
  });

  it('merged state gets sevOk, not sevInfo or sevWarn', () => {
    const { container } = renderRow({ ...baseItem, state: 'merged' });
    const pin = container.querySelector(`.${styles.notifPin}`);

    expect(pin?.classList.contains(styles.sevOk)).toBe(true);
    expect(pin?.classList.contains(styles.sevInfo)).toBe(false);
    expect(pin?.classList.contains(styles.sevWarn)).toBe(false);
  });

  it('closed state gets sevWarn, not sevInfo or sevOk', () => {
    const { container } = renderRow({ ...baseItem, state: 'closed' });
    const pin = container.querySelector(`.${styles.notifPin}`);

    expect(pin?.classList.contains(styles.sevWarn)).toBe(true);
    expect(pin?.classList.contains(styles.sevInfo)).toBe(false);
    expect(pin?.classList.contains(styles.sevOk)).toBe(false);
  });
});

describe('GitHubActivityRow — linked vs plain title', () => {
  it('renders an anchor with target=_blank and rel=noreferrer when url is present', () => {
    renderRow(baseItem);

    const link = screen.getByRole('link', { name: 'Open issue title' });
    expect(link).toHaveAttribute('href', baseItem.url as string);
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noreferrer');
  });

  it('renders plain text, not a link, when url is null', () => {
    renderRow({ ...baseItem, url: null });

    expect(screen.queryByRole('link', { name: 'Open issue title' })).not.toBeInTheDocument();
    expect(screen.getByText('Open issue title')).toBeInTheDocument();
  });
});

describe('GitHubActivityRow — timestamp', () => {
  it('renders a relative time string in the time column', () => {
    const { container } = renderRow(baseItem);
    const timeEl = container.querySelector(`.${styles.notifTime}`);

    expect(timeEl).not.toBeNull();
    expect(timeEl?.textContent).toBeTruthy();
  });
});
