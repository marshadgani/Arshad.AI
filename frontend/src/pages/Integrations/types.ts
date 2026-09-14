/**
 * Wire shape of one integration card, as returned by
 * GET /api/v1/integrations (see backend/src/integrations/presenters.py,
 * which is the single place that shape is produced).
 *
 * Lives in its own module so the page, the card, and the modals can all
 * agree on it without any of them importing the others.
 */

export type IntegrationKind =
  | 'personal_oauth'
  | 'personal_apikey'
  | 'personal_push'
  | 'project_apikey'
  | 'static';

export type IntegrationStatus =
  | 'connected'
  | 'disconnected'
  | 'error'
  | 'expired'
  | 'coming_soon';

/**
 * What disconnecting will do at the third party, as declared by the
 * provider in backend/src/integrations/base.py.
 *
 * `detail` is written to be shown to the user verbatim — when
 * `supported` is false it names the manual step they must take (remove
 * the app in Spotify's settings, uninstall from Shopify admin, delete
 * the key in the provider's dashboard). It exists because the disconnect
 * dialog previously told every user their credentials were "revoked with
 * the provider", which was true for none of them.
 */
export interface UpstreamRevocation {
  supported: boolean;
  detail: string;
}

export interface IntegrationItem {
  slug: string;
  kind: IntegrationKind;
  display_name: string;
  category: string;
  description: string;
  docs_url: string | null;
  icon: string;
  status: IntegrationStatus;
  last_synced_at: string | null;
  last_error: string | null;
  extra: Record<string, unknown>;
  coming_soon: boolean;
  coming_soon_reason: string | null;
  connect_prompt?: { label: string; placeholder: string } | null;
  upstream_revocation: UpstreamRevocation;
}
