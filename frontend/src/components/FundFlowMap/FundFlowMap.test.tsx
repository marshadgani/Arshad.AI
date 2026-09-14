/**
 * FundFlowMap — honesty-labelling tests.
 *
 * FundFlowMap renders a large, hand-authored static SVG diagram via
 * dangerouslySetInnerHTML. It has zero data binding to any real account or
 * transfer data. These tests guard the honesty signals added so the diagram
 * never misrepresents itself as live: a visible "Manual" badge, a
 * plain-English caption stating it is not connected to live data, a
 * keyboard-accessible scroll region described by that caption for assistive
 * technology, and the absence of any wording that would contradict that
 * disclosure. They also guard against silent regression of the legend and
 * the rendered diagram itself, and the source-level invariant that keeps
 * the dangerouslySetInnerHTML sink static.
 */

import { render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import FundFlowMap from './FundFlowMap';

describe('FundFlowMap', () => {
  it('renders the "Manual" badge', () => {
    render(<FundFlowMap />);

    expect(screen.getByText('Manual')).toBeInTheDocument();
  });

  it('badge and header meta do not use wording that implies live/synced data', () => {
    render(<FundFlowMap />);

    // Scoped to the badge and the section's meta line, not the full page:
    // the caption legitimately contains "live"/"synced" as part of the
    // negation ("not connected to any live ... not synced records"). A
    // regression here (e.g. someone changing "Manual" to "Live", or adding
    // a "synced" status badge) would directly contradict that disclosure.
    const badge = screen.getByText('Manual');
    const meta = screen.getByText(/updated/i);

    [badge, meta].forEach((el) => {
      [/\blive\b/i, /real-time/i, /\bsynced\b/i, /auto-update/i].forEach((pattern) => {
        expect(el.textContent).not.toMatch(pattern);
      });
    });
  });

  it('renders a caption stating the diagram is not connected to live data', () => {
    render(<FundFlowMap />);

    expect(
      screen.getByText(/not connected to any live bank or account data/i)
    ).toBeInTheDocument();
  });

  it('exposes the diagram as a keyboard-reachable group described by the caption', () => {
    render(<FundFlowMap />);

    const group = screen.getByRole('group', { name: /fund flow diagram/i });
    expect(group).toHaveAttribute('tabindex', '0');

    const describedById = group.getAttribute('aria-describedby');
    expect(describedById).toBeTruthy();

    const caption = document.getElementById(describedById as string);
    expect(caption).not.toBeNull();
    expect(caption?.textContent).toMatch(/not connected/i);
  });

  it('renders the SVG diagram inside the described group (dangerouslySetInnerHTML sink is populated)', () => {
    render(<FundFlowMap />);

    const group = screen.getByRole('group', { name: /fund flow diagram/i });
    const svg = group.querySelector('svg');

    expect(svg).not.toBeNull();
    // A regression that empties or breaks the static markup would still
    // leave the wrapper in the DOM, so assert it actually has content.
    expect(group.querySelectorAll('rect, line, text').length).toBeGreaterThan(0);
  });

  it('renders the legend', () => {
    render(<FundFlowMap />);

    expect(screen.getByText('Saudi Bank')).toBeInTheDocument();
  });

  it('renders all 12 legend labels exactly once (regression guard)', () => {
    render(<FundFlowMap />);

    const expectedLabels = [
      'Income Source',
      'Vendor',
      'Saudi Bank',
      'Exchange',
      'NRE Account',
      'NRO Account',
      'Savings Account',
      'Family',
      'Credit Card',
      'Investment',
      'Subscription',
      'Expense',
    ];

    expectedLabels.forEach((label) => {
      expect(screen.getAllByText(label)).toHaveLength(1);
    });
  });

  it('has no inline style on the Manual badge or the caption', () => {
    render(<FundFlowMap />);

    expect(screen.getByText('Manual')).not.toHaveAttribute('style');
    expect(
      screen.getByText(/not connected to any live bank or account data/i)
    ).not.toHaveAttribute('style');
  });
});

describe('fundFlowDiagram.ts source-text invariant', () => {
  const source = readFileSync(
    resolve(dirname(fileURLToPath(import.meta.url)), './fundFlowDiagram.ts'),
    'utf-8'
  );

  it('contains no template-literal interpolation (${...})', () => {
    // The SVG string is passed to dangerouslySetInnerHTML and must stay
    // fully static; the trustedStaticSvg tagged template enforces this at
    // compile time (any ${} fails to typecheck), and this is a runtime/CI
    // guard as defence-in-depth against that being bypassed later.
    expect(source).not.toMatch(/\$\{/);
  });

  it('exports FUND_FLOW_DIAGRAM_SVG via the trustedStaticSvg tag, not a plain string literal', () => {
    expect(source).toMatch(/trustedStaticSvg`/);
  });
});
