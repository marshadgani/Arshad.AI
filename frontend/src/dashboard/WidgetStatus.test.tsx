import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { SourceBadge, WidgetStatus } from './WidgetStatus';

describe('WidgetStatus', () => {
  it('renders skeleton rows and an accessible loading announcement while loading', () => {
    render(
      <WidgetStatus isLoading error={null} isEmpty={false} emptyMessage="empty">
        <div>content</div>
      </WidgetStatus>
    );
    expect(screen.getByText('Loading…')).toBeInTheDocument();
    expect(screen.queryByText('content')).not.toBeInTheDocument();
  });

  it('renders an alert with the error message when the request failed', () => {
    render(
      <WidgetStatus isLoading={false} error={new Error('network down')} isEmpty={false} emptyMessage="empty">
        <div>content</div>
      </WidgetStatus>
    );
    expect(screen.getByRole('alert')).toHaveTextContent('network down');
  });

  it('renders the empty message when there is no error and no data', () => {
    render(
      <WidgetStatus isLoading={false} error={null} isEmpty emptyMessage="Nothing here">
        <div>content</div>
      </WidgetStatus>
    );
    expect(screen.getByText('Nothing here')).toBeInTheDocument();
  });

  it('renders children once loaded, non-empty, and error-free', () => {
    render(
      <WidgetStatus isLoading={false} error={null} isEmpty={false} emptyMessage="empty">
        <div>content</div>
      </WidgetStatus>
    );
    expect(screen.getByText('content')).toBeInTheDocument();
  });
});

describe('SourceBadge', () => {
  it('renders nothing when mode is undefined', () => {
    const { container } = render(<SourceBadge mode={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders "Live" for mode="live"', () => {
    render(<SourceBadge mode="live" />);
    expect(screen.getByText('Live')).toBeInTheDocument();
  });

  it('renders "Demo" for mode="seed"', () => {
    render(<SourceBadge mode="seed" />);
    expect(screen.getByText('Demo')).toBeInTheDocument();
  });
});
