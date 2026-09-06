import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';

import { AuthProvider } from '../auth/AuthContext';
import AppLayout from './AppLayout';
import styles from './AppLayout.module.css';

function renderAt(path: string) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: false,
    status: 401,
    json: async () => ({}),
  }) as unknown as typeof fetch;

  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          <Route
            path="*"
            element={
              <AppLayout>
                <div data-testid="route-content">content</div>
              </AppLayout>
            }
          />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('AppLayout', () => {
  it('renders no ChatBar composer on a non-chat route (regression)', () => {
    renderAt('/');
    expect(screen.queryByPlaceholderText(/ask arshad\.ai/i)).not.toBeInTheDocument();
  });

  it('reserves FAB padding on a non-chat route', () => {
    renderAt('/');
    expect(screen.getByTestId('route-content').parentElement).toHaveClass(styles.contentFabPad);
  });

  it('does not reserve FAB padding on /chat', () => {
    renderAt('/chat/abc');
    expect(screen.getByTestId('route-content').parentElement).not.toHaveClass(styles.contentFabPad);
  });
});
