import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

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

afterEach(() => vi.restoreAllMocks());

describe('Admin › System status', () => {
  it('shows each check and the overall state', async () => {
    mockApi([
      ...baseRoutes,
      { method: 'GET', path: '/api/v1/users/me', body: user } as Route,
      {
        method: 'GET',
        path: '/api/v1/admin/status',
        body: {
          checked_at: '2026-10-11T12:00:00Z',
          overall: 'critical',
          version: '0.27.0',
          checks: [
            {
              key: 'database',
              name: 'Database',
              state: 'ok',
              message: '42.0 MB, 9 of 100 connections in use.',
              metrics: {},
            },
            {
              key: 'worker',
              name: 'Background worker',
              state: 'critical',
              message: "The worker hasn't checked in for over 3 minutes.",
              metrics: {},
            },
            { key: 'queue', name: 'Job queue', state: 'warning', message: '150 jobs waiting.', metrics: {} },
          ],
        },
      },
    ]);
    renderAt('/admin?tab=status');
    expect(await screen.findByText('Something is not working.')).toBeInTheDocument();
    const items = within(screen.getByRole('list', { name: 'Checks' })).getAllByRole('listitem');
    expect(items.map((i) => i.textContent)).toEqual([
      expect.stringContaining('OKDatabase42.0 MB'),
      expect.stringContaining('ProblemBackground worker'),
      expect.stringContaining('Needs attentionJob queue150 jobs waiting.'),
    ]);
  });
});
