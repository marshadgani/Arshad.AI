import { useState } from 'react';

import { IntegrationApiError, connectIntegration } from '../../api/integrations';
import type { IntegrationItem } from './types';

/**
 * Owns the "connect an integration" conversation and nothing else.
 *
 * Connecting takes one of four shapes depending on the provider kind:
 * straight to OAuth, an API-key prompt first, an account-identifier
 * prompt first (`connect_prompt`), or a one-time token handed back to
 * the user afterwards (personal_push). That's six pieces of modal state
 * and three submit handlers, which used to sit inline in the page beside
 * the unrelated sync and disconnect flows.
 *
 * Exposes one descriptor per modal so the page can render them without
 * knowing which provider kinds map to which prompt.
 */

interface ConnectFlowOptions {
  /** Marks a slug as having an action in flight (shared with sync/disconnect). */
  setBusySlug: (slug: string | null) => void;
  onToast: (message: string) => void;
  refetch: () => Promise<void>;
}

export function useConnectFlow({ setBusySlug, onToast, refetch }: ConnectFlowOptions) {
  const [apiKeyItem, setApiKeyItem] = useState<IntegrationItem | null>(null);
  const [apiKeyDraft, setApiKeyDraft] = useState('');
  const [apiKeyErr, setApiKeyErr] = useState<string | null>(null);

  const [promptItem, setPromptItem] = useState<IntegrationItem | null>(null);
  const [promptDraft, setPromptDraft] = useState('');
  const [promptErr, setPromptErr] = useState<string | null>(null);

  const [ingestToken, setIngestToken] = useState<{
    item: IntegrationItem;
    token: string;
  } | null>(null);

  const closeApiKey = () => setApiKeyItem(null);
  const closePrompt = () => setPromptItem(null);
  const closeIngestToken = () => setIngestToken(null);

  const begin = async (item: IntegrationItem) => {
    if (item.kind === 'project_apikey') {
      setApiKeyItem(item);
      setApiKeyDraft('');
      setApiKeyErr(null);
      return;
    }
    if (item.kind === 'personal_oauth' && item.connect_prompt) {
      setPromptItem(item);
      setPromptDraft('');
      setPromptErr(null);
      return;
    }
    // personal_oauth without a prompt, and personal_push: POST connect
    // directly and follow whatever the provider hands back.
    setBusySlug(item.slug);
    try {
      const { redirect_url: url, ingest_token: token } = await connectIntegration(
        item.slug,
      );
      if (url) {
        window.location.href = url;
        return;
      }
      if (token) {
        setIngestToken({ item, token });
        await refetch();
        return;
      }
      onToast(`${item.display_name} connected`);
      await refetch();
    } catch (e: unknown) {
      onToast(`Connect failed: ${(e as Error).message}`);
    } finally {
      setBusySlug(null);
    }
  };

  const submitApiKey = async () => {
    if (!apiKeyItem) return;
    if (!apiKeyDraft.trim()) {
      setApiKeyErr('API key required');
      return;
    }
    setBusySlug(apiKeyItem.slug);
    try {
      await connectIntegration(apiKeyItem.slug, { api_key: apiKeyDraft.trim() });
      onToast(`${apiKeyItem.display_name} connected`);
      setApiKeyItem(null);
      setApiKeyDraft('');
      await refetch();
    } catch (e: unknown) {
      setApiKeyErr((e as Error).message);
    } finally {
      setBusySlug(null);
    }
  };

  const submitPrompt = async () => {
    if (!promptItem) return;
    if (!promptDraft.trim()) {
      setPromptErr('Store domain required');
      return;
    }
    setBusySlug(promptItem.slug);
    try {
      const { redirect_url: url } = await connectIntegration(promptItem.slug, {
        shop: promptDraft.trim(),
      }).catch((e: unknown) => {
        // A failed HMAC or a skewed timestamp means the nonce this modal
        // was opened with is no longer usable — the user's fix is to start
        // the flow again, which the raw upstream message does not say.
        const code = e instanceof IntegrationApiError ? e.code : null;
        if (code === 'invalid_hmac' || code === 'timestamp_skew') {
          throw new Error('Authentication failed. Please click Connect again.');
        }
        throw e;
      });
      if (url) {
        window.location.href = url;
        return;
      }
      onToast(`${promptItem.display_name} connected`);
      setPromptItem(null);
      setPromptDraft('');
      await refetch();
    } catch (e: unknown) {
      setPromptErr((e as Error).message);
    } finally {
      setBusySlug(null);
    }
  };

  return {
    begin,
    apiKey: {
      item: apiKeyItem,
      value: apiKeyDraft,
      error: apiKeyErr,
      setValue: setApiKeyDraft,
      submit: submitApiKey,
      close: closeApiKey,
    },
    prompt: {
      item: promptItem,
      value: promptDraft,
      error: promptErr,
      setValue: setPromptDraft,
      submit: submitPrompt,
      close: closePrompt,
    },
    ingestToken: { value: ingestToken, close: closeIngestToken },
  };
}
