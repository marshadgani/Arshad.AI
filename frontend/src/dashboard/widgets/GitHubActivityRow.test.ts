/**
 * Characterisation tests for activityMetaLine. The same rules were already
 * covered indirectly through GitHubActivityCard's DOM queries; these assert
 * them directly at the seam so the string contract is pinned without a
 * render.
 */

import { describe, expect, it } from 'vitest';

import { type GitHubActivityRes } from '../useDashboardData';
import { activityMetaLine } from './GitHubActivityRow';

const baseItem: GitHubActivityRes = {
  id: '1',
  title: 'Fix the login bug',
  url: 'https://github.com/owner/repo/issues/42',
  number: 42,
  repository: 'owner/repo',
  kind: 'issue',
  state: 'open',
  isDraft: false,
  author: 'arshad',
  updatedAt: '2026-09-13T12:00:00.000Z',
};

describe('activityMetaLine', () => {
  it('joins repository, number, kind, state and author', () => {
    expect(activityMetaLine(baseItem)).toBe('owner/repo #42 · Issue · open · arshad');
  });

  it('omits the number when it is null', () => {
    expect(activityMetaLine({ ...baseItem, number: null })).toBe(
      'owner/repo · Issue · open · arshad',
    );
  });

  it('labels pull requests as PR', () => {
    expect(activityMetaLine({ ...baseItem, kind: 'pr' })).toContain('· PR ·');
  });

  it('always includes the state word so colour is not the only signal', () => {
    expect(activityMetaLine({ ...baseItem, state: 'merged' })).toContain('merged');
  });

  it('inserts draft only when isDraft is true', () => {
    expect(activityMetaLine({ ...baseItem, kind: 'pr', isDraft: true })).toContain(
      '· draft ·',
    );
    expect(activityMetaLine(baseItem)).not.toContain('draft');
  });

  it('leaves no dangling separator when the author is null', () => {
    expect(activityMetaLine({ ...baseItem, author: null })).toBe(
      'owner/repo #42 · Issue · open',
    );
  });
});
