/**
 * OntologyEntityList — the four required states plus filter wiring.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { OntologyEntity } from '../../../types/ontology';
import { OntologyEntityList } from './OntologyEntityList';

function entity(overrides: Partial<OntologyEntity> = {}): OntologyEntity {
  return {
    id: '1',
    domain: 'calendar',
    entity_type: 'Event',
    stable_entity_id: 'event:abc',
    display_name: 'Standup',
    vault_path: 'Arshad.AI/Calendar/Standup.md',
    sync_state: 'synced',
    conflict_reason: null,
    tags: ['arshad-ai/calendar'],
    source_updated_at: '2026-09-13T00:00:00Z',
    last_synced_at: '2026-09-13T00:05:00Z',
    ...overrides,
  };
}

const noop = vi.fn();

function baseProps() {
  return {
    entities: [],
    isLoading: false,
    error: null,
    hasMore: false,
    onLoadMore: noop,
    entityType: '',
    onEntityTypeChange: noop,
    syncState: '',
    onSyncStateChange: noop,
    activeDomain: null,
  };
}

describe('OntologyEntityList', () => {
  it('shows a busy list while loading with no entities yet', () => {
    render(<OntologyEntityList {...baseProps()} isLoading />);
    expect(screen.getByRole('status', { hidden: true })).toBeInTheDocument();
  });

  it('shows the error panel when loading failed with no entities', () => {
    render(<OntologyEntityList {...baseProps()} error={new Error('boom')} />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('shows the empty state when filters match nothing', () => {
    render(<OntologyEntityList {...baseProps()} />);
    expect(screen.getByText('No matching entities')).toBeInTheDocument();
  });

  it('renders a row per entity with its type, name, and sync state', () => {
    render(
      <OntologyEntityList {...baseProps()} entities={[entity(), entity({ id: '2', display_name: 'Retro' })]} />,
    );
    expect(screen.getByText('Standup')).toBeInTheDocument();
    expect(screen.getByText('Retro')).toBeInTheDocument();
    expect(screen.getAllByText('Synced')).toHaveLength(2);
  });

  it('shows a conflict reason when present', () => {
    render(
      <OntologyEntityList
        {...baseProps()}
        entities={[entity({ sync_state: 'conflict', conflict_reason: 'foreign_path' })]}
      />,
    );
    expect(screen.getByText('Conflict: foreign_path')).toBeInTheDocument();
  });

  it('shows a "Load more" button only when hasMore is true', () => {
    const { rerender } = render(
      <OntologyEntityList {...baseProps()} entities={[entity()]} hasMore={false} />,
    );
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull();

    rerender(<OntologyEntityList {...baseProps()} entities={[entity()]} hasMore />);
    expect(screen.getByRole('button', { name: 'Load more' })).toBeInTheDocument();
  });

  it('calls onLoadMore when the load-more button is clicked', async () => {
    const onLoadMore = vi.fn();
    const user = userEvent.setup();
    render(
      <OntologyEntityList {...baseProps()} entities={[entity()]} hasMore onLoadMore={onLoadMore} />,
    );
    await user.click(screen.getByRole('button', { name: 'Load more' }));
    expect(onLoadMore).toHaveBeenCalledTimes(1);
  });

  it('calls onEntityTypeChange when the type filter changes', async () => {
    const onEntityTypeChange = vi.fn();
    const user = userEvent.setup();
    render(<OntologyEntityList {...baseProps()} onEntityTypeChange={onEntityTypeChange} />);
    await user.selectOptions(screen.getByLabelText('Type'), 'Person');
    expect(onEntityTypeChange).toHaveBeenCalledWith('Person');
  });

  it('calls onSyncStateChange when the sync-state filter changes', async () => {
    const onSyncStateChange = vi.fn();
    const user = userEvent.setup();
    render(<OntologyEntityList {...baseProps()} onSyncStateChange={onSyncStateChange} />);
    await user.selectOptions(screen.getByLabelText('Sync state'), 'conflict');
    expect(onSyncStateChange).toHaveBeenCalledWith('conflict');
  });

  it('shows the active domain as a chip', () => {
    render(<OntologyEntityList {...baseProps()} activeDomain="github" entities={[entity()]} />);
    expect(screen.getByText('github')).toBeInTheDocument();
  });
});
