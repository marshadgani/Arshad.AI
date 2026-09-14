/**
 * ConnectResultBanner — success vs. error semantics and dismissal.
 *
 * Queries are by role and label, never by CSS class, per
 * .claude/rules/frontend.md.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ConnectResultBanner } from './ConnectResultBanner';

describe('ConnectResultBanner', () => {
  it('announces a success outcome politely via role="status"', () => {
    render(
      <ConnectResultBanner
        kind="success"
        title="GitHub connected"
        onDismiss={vi.fn()}
        autoDismissMs={0}
      />,
    );
    expect(screen.getByRole('status')).toHaveTextContent('GitHub connected');
  });

  it('interrupts with role="alert" for a failure outcome', () => {
    render(
      <ConnectResultBanner
        kind="error"
        title="Connect failed"
        message="you cancelled the provider consent screen"
        onDismiss={vi.fn()}
        autoDismissMs={0}
      />,
    );
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Connect failed');
    expect(alert).toHaveTextContent('you cancelled the provider consent screen');
  });

  it('calls onDismiss when the dismiss button is clicked', async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    render(
      <ConnectResultBanner
        kind="success"
        title="Gmail connected"
        onDismiss={onDismiss}
        autoDismissMs={0}
      />,
    );
    await user.click(screen.getByRole('button', { name: /dismiss notification/i }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('auto-dismisses after the configured timeout', () => {
    vi.useFakeTimers();
    const onDismiss = vi.fn();
    render(
      <ConnectResultBanner
        kind="success"
        title="Google Calendar connected"
        onDismiss={onDismiss}
        autoDismissMs={1000}
      />,
    );
    expect(onDismiss).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1000);
    expect(onDismiss).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });
});
