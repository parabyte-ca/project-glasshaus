import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from './App';
import { baseRoutes, mockApi, user, type Route } from './test/mockApi';

function renderAt(path: string) {
  window.history.pushState({}, '', path);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

describe('Workspaces', () => {
  beforeEach(() => localStorage.setItem('glasshaus.access', 'tok'));
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('renames a workspace from the Home page', async () => {
    let sent: unknown;
    mockApi([
      ...baseRoutes,
      { method: 'GET', path: '/api/v1/users/me', body: user } as Route,
      {
        method: 'PATCH',
        path: '/api/v1/workspaces/w1',
        handler: async (req) => {
          sent = await req.json();
          return { id: 'w1', name: 'Delivery', slug: 'main', description: '', created_at: '' };
        },
      },
    ]);
    renderAt('/');
    await userEvent.click(await screen.findByRole('button', { name: 'Rename workspace Main' }));
    const input = screen.getByLabelText('Workspace name');
    await userEvent.clear(input);
    await userEvent.type(input, 'Delivery');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(sent).toEqual({ name: 'Delivery' }));
  });
});
