import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import DisconnectConfirmModal from './DisconnectConfirmModal';
import type { IntegrationItem } from './types';

/**
 * These tests exist for a shipped bug, not for coverage.
 *
 * This dialog used to read "Stored credentials ... will be revoked with
 * the provider and permanently deleted" for every integration, while the
 * backend revoked nothing at any provider. The claim is now the
 * provider's own (`upstream_revocation.detail`, rendered verbatim), so
 * what is worth asserting is that the component does not reintroduce a
 * blanket promise of its own and does not drop the provider's wording.
 */

function makeItem(overrides: Partial<IntegrationItem> = {}): IntegrationItem {
  return {
    slug: 'fitbit',
    kind: 'personal_oauth',
    display_name: 'Fitbit',
    category: 'Health',
    description: 'Daily activity.',
    docs_url: null,
    icon: 'fitbit',
    status: 'connected',
    last_synced_at: null,
    last_error: null,
    extra: {},
    coming_soon: false,
    coming_soon_reason: null,
    upstream_revocation: {
      supported: true,
      detail: 'POST https://api.fitbit.com/oauth2/revoke — Fitbit invalidates the tokens.',
    },
    ...overrides,
  };
}

const noop = () => {};

describe('DisconnectConfirmModal', () => {
  it("shows the provider's own statement about upstream revocation", () => {
    const item = makeItem();
    render(
      <DisconnectConfirmModal
        item={item}
        submitting={false}
        error={null}
        onConfirm={noop}
        onClose={noop}
      />,
    );

    expect(screen.getByText(item.upstream_revocation.detail)).toBeInTheDocument();
  });

  it('tells the user what they must do themselves when revocation is unsupported', () => {
    const detail =
      'Spotify provides no way for an app to revoke its own access. ' +
      'Remove Arshad.AI at spotify.com/account/apps to complete the revocation.';
    render(
      <DisconnectConfirmModal
        item={makeItem({
          display_name: 'Spotify',
          upstream_revocation: { supported: false, detail },
        })}
        submitting={false}
        error={null}
        onConfirm={noop}
        onClose={noop}
      />,
    );

    expect(screen.getByText(detail)).toBeInTheDocument();
    // The regression itself: no wording anywhere in the dialog may claim
    // the provider revoked anything, because for this provider nothing
    // was revoked.
    const dialog = screen.getByRole('dialog');
    expect(dialog.textContent).not.toMatch(/will be revoked with the provider/i);
    expect(dialog.textContent).toMatch(/permanently deleted from Arshad\.AI/i);
  });

  it('disables both buttons while the request is in flight', () => {
    render(
      <DisconnectConfirmModal
        item={makeItem()}
        submitting
        error={null}
        onConfirm={noop}
        onClose={noop}
      />,
    );

    expect(screen.getByRole('button', { name: /revoking/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /cancel/i })).toBeDisabled();
  });

  it('offers a retry without losing the confirmation context after a failure', () => {
    const onConfirm = vi.fn();
    render(
      <DisconnectConfirmModal
        item={makeItem()}
        submitting={false}
        error="Upstream revocation failed"
        onConfirm={onConfirm}
        onClose={noop}
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('Upstream revocation failed');
    expect(screen.getByRole('button', { name: /try again/i })).toBeEnabled();
  });
});
