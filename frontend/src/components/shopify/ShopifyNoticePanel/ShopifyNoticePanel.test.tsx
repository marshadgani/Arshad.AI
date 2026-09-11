/**
 * ShopifyNoticePanel — connect / re-auth notice rendering.
 *
 * The panel is used for both the "not connected" and "needs re-auth" states
 * of the Shopify page. Both states pass different props; the panel must
 * render every prop it receives.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ShopifyNoticePanel } from './ShopifyNoticePanel';

describe('ShopifyNoticePanel', () => {
  it('renders the title as a heading', () => {
    render(
      <ShopifyNoticePanel
        icon="🛒"
        title="Connect Shopify"
        description="Link your store."
        actionLabel="Connect"
        actionHref="/integrations"
      />,
    );

    expect(screen.getByRole('heading', { name: 'Connect Shopify' })).toBeInTheDocument();
  });

  it('renders the description text', () => {
    render(
      <ShopifyNoticePanel
        icon="🛒"
        title="Connect Shopify"
        description="Link your Shopify store to see revenue data."
        actionLabel="Connect"
        actionHref="/integrations"
      />,
    );

    expect(screen.getByText('Link your Shopify store to see revenue data.')).toBeInTheDocument();
  });

  it('renders the action as a link pointing to the given href', () => {
    render(
      <ShopifyNoticePanel
        icon="⚠️"
        title="Reconnect Shopify"
        description="Your session has expired."
        actionLabel="Reconnect Shopify"
        actionHref="/integrations"
      />,
    );

    const link = screen.getByRole('link', { name: 'Reconnect Shopify' });
    expect(link).toHaveAttribute('href', '/integrations');
  });

  it('renders the icon text in the panel', () => {
    render(
      <ShopifyNoticePanel
        icon="🛒"
        title="Connect Shopify"
        description="Link your store."
        actionLabel="Connect"
        actionHref="/integrations"
      />,
    );

    expect(screen.getByText('🛒')).toBeInTheDocument();
  });
});
