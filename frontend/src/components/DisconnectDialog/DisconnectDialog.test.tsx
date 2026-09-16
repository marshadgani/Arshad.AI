import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import DisconnectDialog from './DisconnectDialog';

describe('DisconnectDialog', () => {
  it('renders revokes copy promising an upstream revoke', () => {
    render(
      <DisconnectDialog
        provider={{ display_name: 'Fitbit', revocation_kind: 'revokes' }}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
        isLoading={false}
      />,
    );
    expect(
      screen.getByText('Stored credentials will be removed and access revoked with Fitbit.'),
    ).toBeInTheDocument();
  });

  it('renders no_revoke copy that does not promise upstream revocation', () => {
    render(
      <DisconnectDialog
        provider={{ display_name: 'Spotify', revocation_kind: 'no_revoke' }}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
        isLoading={false}
      />,
    );
    expect(screen.getByText(/does not offer a revoke API/)).toBeInTheDocument();
  });

  it('renders no_credential copy noting sign-in is unaffected', () => {
    render(
      <DisconnectDialog
        provider={{ display_name: 'Gmail', revocation_kind: 'no_credential' }}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
        isLoading={false}
      />,
    );
    expect(screen.getByText(/Your sign-in is unaffected/)).toBeInTheDocument();
  });

  it('calls onCancel when Cancel is clicked', () => {
    const onCancel = vi.fn();
    render(
      <DisconnectDialog
        provider={{ display_name: 'Render', revocation_kind: 'no_revoke' }}
        onConfirm={vi.fn()}
        onCancel={onCancel}
        isLoading={false}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('calls onConfirm when Disconnect is clicked', () => {
    const onConfirm = vi.fn();
    render(
      <DisconnectDialog
        provider={{ display_name: 'Render', revocation_kind: 'no_revoke' }}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
        isLoading={false}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Disconnect' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('calls onCancel on Escape', () => {
    const onCancel = vi.fn();
    render(
      <DisconnectDialog
        provider={{ display_name: 'Render', revocation_kind: 'no_revoke' }}
        onConfirm={vi.fn()}
        onCancel={onCancel}
        isLoading={false}
      />,
    );
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('disables the confirm button while loading', () => {
    render(
      <DisconnectDialog
        provider={{ display_name: 'Render', revocation_kind: 'no_revoke' }}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
        isLoading
      />,
    );
    expect(screen.getByRole('button', { name: 'Disconnecting…' })).toBeDisabled();
  });
});
