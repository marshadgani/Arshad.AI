/**
 * FundFlowMap — honesty-labelling tests.
 *
 * This diagram depicts real personal financial topology but is hand-drawn
 * and never wired to any live account feed. These tests guard that the
 * "Static" disclosure stays visible and accessible, the staleness date is
 * derived deterministically from a single source of truth (MAP_META), the
 * diagram exposes an accessible name, and the component never fetches.
 */

import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import FundFlowMap from './FundFlowMap';
import { formatReviewed } from './mapMeta';

describe('FundFlowMap', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the "Static" badge label', () => {
    render(<FundFlowMap />);

    expect(screen.getByText('Static')).toBeInTheDocument();
  });

  it('discloses in the caption that the diagram is not synced to live data', () => {
    render(<FundFlowMap />);

    const caption = screen.getByText(/not synced to live account data/i);
    expect(caption).toBeInTheDocument();
    expect(caption.textContent).toMatch(/last reviewed \d{1,2} [A-Z][a-z]{2} \d{4}/);
  });

  it('formatReviewed is a deterministic, locale-independent formatter', () => {
    expect(formatReviewed('2026-09-14')).toBe('14 Sep 2026');
    expect(formatReviewed('2026-01-01')).toBe('1 Jan 2026');
  });

  it('gives the diagram a single accessible name', () => {
    render(<FundFlowMap />);

    expect(screen.getByRole('img', { name: /fund flow/i })).toBeInTheDocument();
  });

  it('hides the badge dot from assistive technology while keeping the label reachable', () => {
    const { container } = render(<FundFlowMap />);

    const dot = container.querySelector('[aria-hidden="true"]');
    expect(dot).toBeInTheDocument();
    expect(screen.getByText('Static')).toBeInTheDocument();
  });

  it('never fetches — this component has no data source', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');

    render(<FundFlowMap />);

    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
