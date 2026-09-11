/**
 * ShopifyPageHeader — title, subtitle and live badge contract.
 *
 * The header is shared by every state of the Shopify page so the h1 never
 * shifts position between loading, error, not-connected and content. The
 * live badge must only appear when `live={true}` is explicit — it would be
 * misleading to pulse while showing a skeleton.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ShopifyPageHeader } from './ShopifyPageHeader';

describe('ShopifyPageHeader', () => {
  it('always renders the "Shopify Store" heading', () => {
    render(<ShopifyPageHeader />);

    expect(screen.getByRole('heading', { name: 'Shopify Store' })).toBeInTheDocument();
  });

  it('does not render a subtitle when none is provided', () => {
    const { container } = render(<ShopifyPageHeader />);

    expect(container.querySelector('p')).toBeNull();
  });

  it('renders the subtitle text when provided', () => {
    render(<ShopifyPageHeader subtitle="My Shop · Today (UTC)" />);

    expect(screen.getByText('My Shop · Today (UTC)')).toBeInTheDocument();
  });

  it('does not render a subtitle when subtitle is null', () => {
    const { container } = render(<ShopifyPageHeader subtitle={null} />);

    expect(container.querySelector('p')).toBeNull();
  });

  it('does not show the Live badge by default', () => {
    render(<ShopifyPageHeader />);

    expect(screen.queryByText('Live')).toBeNull();
  });

  it('shows the Live badge when live={true}', () => {
    render(<ShopifyPageHeader live />);

    expect(screen.getByText('Live')).toBeInTheDocument();
  });

  it('does not show the Live badge when live={false} is explicit', () => {
    render(<ShopifyPageHeader live={false} />);

    expect(screen.queryByText('Live')).toBeNull();
  });
});
