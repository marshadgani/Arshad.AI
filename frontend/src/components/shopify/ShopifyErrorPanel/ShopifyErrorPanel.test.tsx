/**
 * ShopifyErrorPanel — alert role and message propagation.
 *
 * The panel exists only to surface a fatal fetch failure. Its sole
 * obligations are: announce itself as an alert so screen readers speak it
 * immediately, and show the exact message the caller provides.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ShopifyErrorPanel } from './ShopifyErrorPanel';

describe('ShopifyErrorPanel', () => {
  it('announces itself as an alert so screen readers speak the error immediately', () => {
    render(<ShopifyErrorPanel message="Something went wrong." />);

    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('displays the message provided by the caller', () => {
    render(<ShopifyErrorPanel message="Failed to load Shopify data. Check backend logs." />);

    expect(
      screen.getByText('Failed to load Shopify data. Check backend logs.'),
    ).toBeInTheDocument();
  });

  it('displays a different message when given a different one', () => {
    render(<ShopifyErrorPanel message="Network timeout." />);

    expect(screen.getByRole('alert')).toHaveTextContent('Network timeout.');
  });
});
