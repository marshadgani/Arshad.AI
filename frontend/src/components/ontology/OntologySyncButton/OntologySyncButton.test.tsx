import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { OntologySyncButton } from './OntologySyncButton';

describe('OntologySyncButton', () => {
  it('calls onSync with dryRun=false by default', async () => {
    const onSync = vi.fn();
    const user = userEvent.setup();
    render(<OntologySyncButton onSync={onSync} isSyncing={false} error={null} />);

    await user.click(screen.getByRole('button', { name: /Sync Ontology/ }));
    expect(onSync).toHaveBeenCalledWith(false);
  });

  it('calls onSync with dryRun=true when the checkbox is checked', async () => {
    const onSync = vi.fn();
    const user = userEvent.setup();
    render(<OntologySyncButton onSync={onSync} isSyncing={false} error={null} />);

    await user.click(screen.getByLabelText('Dry run'));
    await user.click(screen.getByRole('button', { name: /Sync Ontology/ }));
    expect(onSync).toHaveBeenCalledWith(true);
  });

  it('disables the button and shows syncing copy while isSyncing', () => {
    render(<OntologySyncButton onSync={vi.fn()} isSyncing error={null} />);
    const button = screen.getByRole('button', { name: /Syncing vault…/ });
    expect(button).toBeDisabled();
  });

  it('shows the error message as an alert', () => {
    render(
      <OntologySyncButton onSync={vi.fn()} isSyncing={false} error={new Error('rate limited')} />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('rate limited');
  });

  it('shows a deduplicated note when a sync is already queued', () => {
    render(
      <OntologySyncButton onSync={vi.fn()} isSyncing={false} error={null} deduplicated />,
    );
    expect(screen.getByText('A sync is already queued.')).toBeInTheDocument();
  });
});
