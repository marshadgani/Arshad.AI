import { useState } from 'react';

import { disconnectIntegration } from '../../api/integrations';
import type { IntegrationItem } from './types';

/**
 * Owns the "disconnect an integration" conversation — the destructive
 * counterpart to useConnectFlow.
 *
 * This used to be a bare `window.confirm()` that promised "Stored
 * credentials will be removed" with no way to show the user whether that
 * actually happened. Now that backend disconnect() really does revoke
 * upstream and scrub local rows (base.py), the confirmation step needs
 * its own loading/error states: revocation is a network call that can
 * fail, and a browser confirm() dialog has no way to show that failure
 * or let the user retry without restarting the whole flow.
 */

interface DisconnectFlowOptions {
  /** Marks a slug as having an action in flight (shared with connect/sync). */
  setBusySlug: (slug: string | null) => void;
  onToast: (message: string) => void;
  refetch: () => Promise<void>;
}

export function useDisconnectFlow({ setBusySlug, onToast, refetch }: DisconnectFlowOptions) {
  const [item, setItem] = useState<IntegrationItem | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const begin = (target: IntegrationItem) => {
    setItem(target);
    setError(null);
    setSubmitting(false);
  };

  const close = () => {
    // Only dismissable once the revoke call has settled — closing mid-flight
    // would let the user believe they cancelled a request that's still
    // in-flight against the provider and the database.
    if (submitting) return;
    setItem(null);
    setError(null);
  };

  const confirm = async () => {
    if (!item) return;
    setSubmitting(true);
    setError(null);
    setBusySlug(item.slug);
    try {
      const status = await disconnectIntegration(item.slug);
      onToast(
        status === 'already_disconnected'
          ? `${item.display_name} was already disconnected`
          : // Not "credentials revoked": deleting our copy is the only
            // part that is true for every provider. Whether anything was
            // revoked at the third party is provider-specific and is
            // stated in the confirmation dialog, which the user has just
            // read — repeating a stronger claim here would undo it.
            `${item.display_name} disconnected — stored credentials deleted`,
      );
      setItem(null);
      await refetch();
    } catch (e: unknown) {
      // IntegrationApiError already carries the backend's human message.
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
      setBusySlug(null);
    }
  };

  return { item, submitting, error, begin, confirm, close };
}
