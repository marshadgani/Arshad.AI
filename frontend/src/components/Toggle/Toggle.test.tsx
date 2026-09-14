import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

import Toggle from './Toggle';

describe('Toggle', () => {
  it('renders as an accessible switch reflecting the checked prop', () => {
    render(
      <Toggle id="t1" label="Reduce motion" checked={false} onChange={vi.fn()} />,
    );
    const control = screen.getByRole('switch', { name: 'Reduce motion' });
    expect(control).toHaveAttribute('aria-checked', 'false');
  });

  it('calls onChange with the inverted value when clicked', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<Toggle id="t2" label="Reduce motion" checked={false} onChange={onChange} />);
    await user.click(screen.getByRole('switch', { name: 'Reduce motion' }));
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it('renders the optional description', () => {
    render(
      <Toggle
        id="t3"
        label="Reduce motion"
        description="Turns off animated transitions."
        checked
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText('Turns off animated transitions.')).toBeInTheDocument();
  });

  it('does not fire onChange when disabled', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<Toggle id="t4" label="Reduce motion" checked={false} onChange={onChange} disabled />);
    await user.click(screen.getByRole('switch', { name: 'Reduce motion' }));
    expect(onChange).not.toHaveBeenCalled();
  });
});
