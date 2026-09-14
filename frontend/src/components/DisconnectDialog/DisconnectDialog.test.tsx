/**
 * DisconnectDialog — copy accuracy per revocation_kind, submit/cancel
 * wiring, error/retry state, and Escape-to-cancel. Queries are by role and
 * label, never by CSS class, per .claude/rules/frontend.md.
 */

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { DisconnectDialog } from './DisconnectDialog';

describe('DisconnectDialog', () => {
  it('promises a full revoke for revocation_kind="revokes"', () => {
    render(
      <DisconnectDialog
        displayName="GitHub"
        revocationKind="revokes"
        isSubmitting={false}
        error={null}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    const dialog = screen.getByRole('alertdialog');
    expect(dialog).toHaveTextContent('Disconnect GitHub?');
    expect(dialog).toHaveTextContent('revoked with GitHub directly');
    expect(screen.getByText('Full revoke')).toBeInTheDocument();
  });

  it('warns about a manual revoke step for revocation_kind="no_revoke"', () => {
    render(
      <DisconnectDialog
        displayName="Notion"
        revocationKind="no_revoke"
        isSubmitting={false}
        error={null}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByRole('alertdialog')).toHaveTextContent('has no revocation API');
    expect(screen.getByText('Manual step required')).toBeInTheDocument();
  });

  it('makes no revoke claim for revocation_kind="no_credential"', () => {
    render(
      <DisconnectDialog
        displayName="Gmail"
        revocationKind="no_credential"
        isSubmitting={false}
        error={null}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    const dialog = screen.getByRole('alertdialog');
    expect(dialog).toHaveTextContent('Your sign-in is unaffected');
    expect(dialog).not.toHaveTextContent('will be deleted');
    expect(screen.getByText('Nothing stored')).toBeInTheDocument();
  });

  it('calls onConfirm when Disconnect is clicked', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <DisconnectDialog
        displayName="GitHub"
        revocationKind="revokes"
        isSubmitting={false}
        error={null}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Disconnect' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('calls onCancel when Cancel is clicked', async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(
      <DisconnectDialog
        displayName="GitHub"
        revocationKind="revokes"
        isSubmitting={false}
        error={null}
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('calls onCancel on Escape, but not while submitting', async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    const { rerender } = render(
      <DisconnectDialog
        displayName="GitHub"
        revocationKind="revokes"
        isSubmitting={true}
        error={null}
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );
    await user.keyboard('{Escape}');
    expect(onCancel).not.toHaveBeenCalled();

    rerender(
      <DisconnectDialog
        displayName="GitHub"
        revocationKind="revokes"
        isSubmitting={false}
        error={null}
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );
    await user.keyboard('{Escape}');
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('shows a busy state and disables both buttons while submitting', () => {
    render(
      <DisconnectDialog
        displayName="GitHub"
        revocationKind="revokes"
        isSubmitting={true}
        error={null}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    const confirmBtn = within(screen.getByRole('alertdialog')).getByRole('button', {
      name: /disconnecting/i,
    });
    expect(confirmBtn).toBeDisabled();
    expect(confirmBtn).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
  });

  it('surfaces a retry state via role="alert" after a failed attempt', () => {
    render(
      <DisconnectDialog
        displayName="GitHub"
        revocationKind="revokes"
        isSubmitting={false}
        error="HTTP 500"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('HTTP 500');
    expect(screen.getByRole('button', { name: 'Retry disconnect' })).toBeInTheDocument();
  });

  it('moves initial focus to Cancel so Enter never accidentally confirms', () => {
    render(
      <DisconnectDialog
        displayName="GitHub"
        revocationKind="revokes"
        isSubmitting={false}
        error={null}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();
  });
});
