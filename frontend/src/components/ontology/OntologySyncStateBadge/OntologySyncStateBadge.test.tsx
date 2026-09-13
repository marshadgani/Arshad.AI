import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { OntologySyncStateBadge } from './OntologySyncStateBadge';

describe('OntologySyncStateBadge', () => {
  it.each([
    ['pending', 'Pending'],
    ['synced', 'Synced'],
    ['deferred', 'Deferred'],
    ['conflict', 'Conflict'],
    ['archived', 'Archived'],
  ])('renders the human label for "%s"', (state, label) => {
    render(<OntologySyncStateBadge state={state} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it('falls back to the raw state string for an unrecognised value', () => {
    render(<OntologySyncStateBadge state="mystery_state" />);
    expect(screen.getByText('mystery_state')).toBeInTheDocument();
  });

  it('sets a descriptive title for assistive tooling', () => {
    render(<OntologySyncStateBadge state="conflict" />);
    expect(screen.getByTitle('Sync state: conflict')).toBeInTheDocument();
  });
});
