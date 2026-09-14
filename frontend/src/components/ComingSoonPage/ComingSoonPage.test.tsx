import { render, screen } from '@testing-library/react';

import ComingSoonPage from './ComingSoonPage';

describe('ComingSoonPage', () => {
  it('renders the title as the level-1 heading', () => {
    render(<ComingSoonPage title="Test Title" emoji="🧪" reason="Test reason." />);
    expect(screen.getByRole('heading', { level: 1, name: 'Test Title' })).toBeInTheDocument();
  });

  it('renders the literal "Coming soon" status text', () => {
    render(<ComingSoonPage title="Test Title" emoji="🧪" reason="Test reason." />);
    expect(screen.getByText('Coming soon')).toBeInTheDocument();
  });

  it('renders the passed reason text', () => {
    render(<ComingSoonPage title="Test Title" emoji="🧪" reason="Test reason." />);
    expect(screen.getByText('Test reason.')).toBeInTheDocument();
  });

  it('marks the decorative emoji as aria-hidden', () => {
    render(<ComingSoonPage title="Test Title" emoji="🧪" reason="Test reason." />);
    expect(screen.getByText('🧪')).toHaveAttribute('aria-hidden', 'true');
  });
});
