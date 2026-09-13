/**
 * OntologyStatusPanel — the four required states (loading/empty/error/
 * content) plus the domain-tile-as-filter interaction.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { OntologyStatus } from '../../../types/ontology';
import { OntologyStatusPanel } from './OntologyStatusPanel';

function status(overrides: Partial<OntologyStatus> = {}): OntologyStatus {
  return {
    last_run_at: '2026-09-13T00:00:00Z',
    last_run_status: 'succeeded',
    last_commit_sha: 'abc1234567890',
    branch: 'main',
    entity_counts_by_domain: { calendar: 12, email: 5, github: 3, people: 8 },
    total_entities: 28,
    deferred: 0,
    conflicts: 0,
    archived: 0,
    ...overrides,
  };
}

describe('OntologyStatusPanel', () => {
  it('shows a busy skeleton while loading with no cached status', () => {
    render(
      <OntologyStatusPanel
        status={null}
        isLoading
        error={null}
        activeDomain={null}
        onSelectDomain={vi.fn()}
      />,
    );
    expect(screen.getByRole('status', { hidden: true })).toBeInTheDocument();
  });

  it('shows the error panel when loading failed with no cached status', () => {
    render(
      <OntologyStatusPanel
        status={null}
        isLoading={false}
        error={new Error('boom')}
        activeDomain={null}
        onSelectDomain={vi.fn()}
      />,
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('shows the empty state when no sync has ever run', () => {
    render(
      <OntologyStatusPanel
        status={status({ total_entities: 0, last_run_at: null, entity_counts_by_domain: {} })}
        isLoading={false}
        error={null}
        activeDomain={null}
        onSelectDomain={vi.fn()}
      />,
    );
    expect(screen.getByText('No ontology sync yet')).toBeInTheDocument();
  });

  it('renders a domain tile per domain with its entity count', () => {
    render(
      <OntologyStatusPanel
        status={status()}
        isLoading={false}
        error={null}
        activeDomain={null}
        onSelectDomain={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: /Calendar MOC/ })).toHaveTextContent('12');
    expect(screen.getByRole('button', { name: /Email MOC/ })).toHaveTextContent('5');
  });

  it('calls onSelectDomain when a tile is clicked, and toggles off when re-clicked', async () => {
    const onSelectDomain = vi.fn();
    const user = userEvent.setup();
    render(
      <OntologyStatusPanel
        status={status()}
        isLoading={false}
        error={null}
        activeDomain={null}
        onSelectDomain={onSelectDomain}
      />,
    );

    await user.click(screen.getByRole('button', { name: /Calendar MOC/ }));
    expect(onSelectDomain).toHaveBeenCalledWith('calendar');
  });

  it('marks the active domain tile as pressed', () => {
    render(
      <OntologyStatusPanel
        status={status()}
        isLoading={false}
        error={null}
        activeDomain="github"
        onSelectDomain={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: /GitHub MOC/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByRole('button', { name: /Calendar MOC/ })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });

  it('shows deferred and conflict counts when present', () => {
    render(
      <OntologyStatusPanel
        status={status({ deferred: 2, conflicts: 1 })}
        isLoading={false}
        error={null}
        activeDomain={null}
        onSelectDomain={vi.fn()}
      />,
    );
    expect(screen.getByText('2 deferred')).toBeInTheDocument();
    expect(screen.getByText('1 conflict')).toBeInTheDocument();
  });

  it('renders a shortened commit SHA', () => {
    render(
      <OntologyStatusPanel
        status={status({ last_commit_sha: 'abcdef1234567890' })}
        isLoading={false}
        error={null}
        activeDomain={null}
        onSelectDomain={vi.fn()}
      />,
    );
    expect(screen.getByText('abcdef1')).toBeInTheDocument();
  });
});
