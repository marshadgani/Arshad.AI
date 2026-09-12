/**
 * LiveBadge — presence and size variant tests.
 *
 * The badge is purely presentational but it carries meaning: it tells the
 * user that the data on screen refreshes automatically. The text "Live" must
 * always be present regardless of size, and the two size props must produce
 * different CSS class names so the layout does not collapse them visually.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { LiveBadge } from './LiveBadge';

describe('LiveBadge', () => {
  it('renders the "Live" label', () => {
    render(<LiveBadge />);

    expect(screen.getByText('Live')).toBeInTheDocument();
  });

  it('defaults to the md size (the badge element carries an md-containing class)', () => {
    const { container } = render(<LiveBadge />);

    // CSS Modules hash class names; the hash includes the source name, so the
    // class string always contains the original identifier even when hashed.
    expect((container.firstChild as Element).className).toContain('md');
  });

  it('applies the sm variant class when size="sm"', () => {
    const { container } = render(<LiveBadge size="sm" />);

    expect((container.firstChild as Element).className).toContain('sm');
  });

  it('sm and md produce distinct class names so the two sizes are visually different', () => {
    const { container: smContainer } = render(<LiveBadge size="sm" />);
    const { container: mdContainer } = render(<LiveBadge size="md" />);

    const smClass = (smContainer.firstChild as Element).className;
    const mdClass = (mdContainer.firstChild as Element).className;
    expect(smClass).not.toBe(mdClass);
  });

  it('hides the decorative pulsing dot from assistive technology', () => {
    const { container } = render(<LiveBadge />);

    const dot = container.querySelector('[aria-hidden="true"]');
    expect(dot).toBeInTheDocument();
  });
});
