import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
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

const status = (over: Record<string, unknown> = {}) => ({
  current: '0.26.0',
  latest: {
    version: '0.27.0',
    name: 'v0.27.0',
    notes: '### Added\n- **Health** page',
    url: 'https://github.com/o/r/releases/tag/v0.27.0',
    published_at: '2026-10-11T10:00:00Z',
  },
  update_available: true,
  checked_at: '2026-10-11T11:00:00Z',
  check_error: null,
  helper: { configured: true, connected: true, last_seen: '2026-10-11T11:59:00Z' },
  upgrade: null,
  can_upgrade: true,
  log: null,
  ...over,
});

beforeEach(() => {
  document.cookie = 'gh_csrf=csrf-123; path=/';
});
afterEach(() => vi.restoreAllMocks());

describe('Admin › Updates', () => {
  it('shows the release notes and lets an owner upgrade', async () => {
    const { calls } = mockApi([
      ...baseRoutes,
      { method: 'GET', path: '/api/v1/users/me', body: user } as Route,
      { method: 'GET', path: '/api/v1/admin/updates', body: status() },
      {
        method: 'POST',
        path: '/api/v1/admin/updates/upgrade',
        body: status({ can_upgrade: false, upgrade: { id: 'x', state: 'requested', to_version: '0.27.0' } }),
      },
    ]);
    renderAt('/admin?tab=updates');
    const notes = await screen.findByRole('region', { name: "What's new in 0.27.0" });
    expect(within(notes).getByText('Health')).toBeInTheDocument();
    await userEvent.click(within(notes).getByRole('button', { name: 'Upgrade to 0.27.0' }));
    const ask = await screen.findByRole('dialog', { name: 'Upgrade to 0.27.0?' });
    await userEvent.click(within(ask).getByRole('button', { name: 'Upgrade' }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/admin/updates/upgrade'))).toBe(true));
    const post = calls.find((c) => c.url.endsWith('/admin/updates/upgrade'))!;
    expect(await post.json()).toEqual({ version: '0.27.0' });
    expect(await screen.findByText(/requested; the server starts it within a minute/)).toBeInTheDocument();
  });

  it('explains how to set up the helper, and only owners get the button', async () => {
    mockApi([
      ...baseRoutes,
      { method: 'GET', path: '/api/v1/users/me', body: user } as Route,
      {
        method: 'GET',
        path: '/api/v1/admin/updates',
        body: status({
          helper: { configured: false, connected: false, last_seen: null },
          can_upgrade: false,
        }),
      },
    ]);
    renderAt('/admin?tab=updates');
    expect(await screen.findByText('sudo ./scripts/upgrade-agent.sh --install')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Upgrade to/ })).not.toBeInTheDocument();

    vi.restoreAllMocks();
    mockApi([
      ...baseRoutes,
      { method: 'GET', path: '/api/v1/users/me', body: { ...user, org_role: 'admin' } } as Route,
      { method: 'GET', path: '/api/v1/admin/updates', body: status({ can_upgrade: false }) },
    ]);
    renderAt('/admin?tab=updates');
    expect((await screen.findAllByText('An owner can upgrade from this page.')).length).toBeGreaterThan(0);
  });
});
