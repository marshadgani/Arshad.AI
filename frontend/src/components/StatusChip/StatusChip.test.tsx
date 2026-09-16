import { render, screen } from '@testing-library/react';

import StatusChip from './StatusChip';

describe('StatusChip', () => {
  it('renders the passed label text', () => {
    render(<StatusChip label="Coming soon" />);
    expect(screen.getByText('Coming soon')).toBeInTheDocument();
  });

  it('marks the decorative dot as aria-hidden so it is absent from the accessibility tree', () => {
    const { container } = render(<StatusChip label="Coming soon" />);
    const dot = container.querySelector('span[aria-hidden="true"]');
    expect(dot).not.toBeNull();
    expect(dot).toHaveAttribute('aria-hidden', 'true');
  });
});
