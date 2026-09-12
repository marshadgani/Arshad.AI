import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import ChatLauncher from './ChatLauncher';

function renderAt(path: string, isNavOpen = false) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ChatLauncher isNavOpen={isNavOpen} />
    </MemoryRouter>,
  );
}

describe('ChatLauncher', () => {
  it('renders a link to /chat on a non-chat route', () => {
    renderAt('/');
    const link = screen.getByRole('link', { name: /open arshad\.ai chat/i });
    expect(link).toHaveAttribute('href', '/chat');
  });

  it('renders nothing when pathname is /chat/abc', () => {
    renderAt('/chat/abc');
    expect(screen.queryByRole('link', { name: /open arshad\.ai chat/i })).not.toBeInTheDocument();
  });

  it('renders nothing when isNavOpen is true', () => {
    renderAt('/', true);
    expect(screen.queryByRole('link', { name: /open arshad\.ai chat/i })).not.toBeInTheDocument();
  });
});
