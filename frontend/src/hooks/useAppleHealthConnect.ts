/**
 * The Apple Health connect flow's state machine, lifted out of
 * AppleHealthCard.
 *
 * The card was doing three unrelated jobs at once: rendering six mutually
 * exclusive dashboard states, owning a modal, and running an async
 * side-effect that mints a one-time secret. This is the third of those —
 * the only part with a lifecycle — so it can be reasoned about (and driven
 * in a test) without rendering a card.
 *
 * The token itself is deliberately held in component state and nowhere
 * else: it is displayed once and is unrecoverable afterwards (the server
 * keeps only a SHA-256 digest). Do not persist it, log it, or lift it into
 * a global store.
 */

import { useCallback, useState } from 'react';

import { connectIntegration } from '../api/integrations';

export const APPLE_HEALTH_SLUG = 'apple_health';

export interface AppleHealthConnectState {
  status: 'idle' | 'connecting' | 'showing-token' | 'error';
  ingestToken: string | null;
  errorMessage: string | null;
}

export interface UseAppleHealthConnectResult {
  state: AppleHealthConnectState;
  /** Discard any previously displayed token and return to the prompt. */
  reset: () => void;
  connect: () => Promise<void>;
}

const IDLE: AppleHealthConnectState = {
  status: 'idle',
  ingestToken: null,
  errorMessage: null,
};

export function useAppleHealthConnect(): UseAppleHealthConnectResult {
  const [state, setState] = useState<AppleHealthConnectState>(IDLE);

  const reset = useCallback(() => setState(IDLE), []);

  const connect = useCallback(async () => {
    setState((s) => ({ ...s, status: 'connecting', errorMessage: null }));
    try {
      const { ingest_token: ingestToken } =
        await connectIntegration(APPLE_HEALTH_SLUG);
      if (!ingestToken) {
        // A push provider that connects without handing back a token has
        // left the user with no way to configure their Shortcut — a silent
        // success here would look connected and never receive data.
        throw new Error('Server did not return an ingest token.');
      }
      setState({ status: 'showing-token', ingestToken, errorMessage: null });
    } catch (e: unknown) {
      setState({
        status: 'error',
        ingestToken: null,
        errorMessage: (e as Error).message,
      });
    }
  }, []);

  return { state, reset, connect };
}
