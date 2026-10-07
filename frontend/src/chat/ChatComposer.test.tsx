import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

import { ChatComposer } from './ChatComposer';

describe('ChatComposer', () => {
  it('starts empty by default', () => {
    render(<ChatComposer disabled={false} onSubmit={vi.fn()} />);
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue('');
  });

  it('prefills a quick-capture draft but does not send it', () => {
    const onSubmit = vi.fn();
    render(<ChatComposer disabled={false} onSubmit={onSubmit} initialDraft="buy milk" />);
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue('buy milk');
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('sends the prefilled draft only when the user presses Send', async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<ChatComposer disabled={false} onSubmit={onSubmit} initialDraft="buy milk" />);
    await user.click(screen.getByRole('button', { name: 'Send' }));
    expect(onSubmit).toHaveBeenCalledWith('buy milk');
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue('');
  });
});
