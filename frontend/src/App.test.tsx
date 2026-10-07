import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from './App';
import { baseRoutes, mockApi, task, user } from './test/mockApi';

function renderAt(path: string) {
  window.history.pushState({}, '', path);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  document.cookie = 'gh_csrf=csrf-123; path=/';
});
afterEach(() => vi.restoreAllMocks());

describe('authentication', () => {
  it('shows the login form, signs in and lands on the project list', async () => {
    let signedIn = false;
    const { calls } = mockApi([
      ...baseRoutes,
      {
        method: 'GET',
        path: '/api/v1/users/me',
        handler: () => (signedIn ? user : undefined),
        get status() {
          return signedIn ? 200 : 401;
        },
      },
      { method: 'POST', path: '/api/v1/auth/refresh', status: 401, body: { detail: 'no session' } },
      {
        method: 'POST',
        path: '/api/v1/auth/login',
        handler: async (req) => {
          signedIn = true;
          expect(await req.json()).toEqual({ email: 'ada@example.com', password: 'pw', organization: null });
          return user;
        },
      },
    ]);
    renderAt('/');
    await userEvent.type(await screen.findByLabelText('Email'), 'ada@example.com');
    await userEvent.type(screen.getByLabelText('Password'), 'pw');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('heading', { name: 'Projects', level: 1 })).toBeInTheDocument();
    expect(await screen.findByTestId('version')).toHaveTextContent('v9.9.9 (abc)');
    expect(calls.filter((c) => c.url.endsWith('/api/v1/auth/refresh'))).toHaveLength(1);
  });

  it('refreshes an expired session once and retries', async () => {
    let refreshed = false;
    mockApi([
      ...baseRoutes,
      {
        method: 'GET',
        path: '/api/v1/users/me',
        handler: () => (refreshed ? user : { detail: 'expired' }),
        get status() {
          return refreshed ? 200 : 401;
        },
      },
      {
        method: 'POST',
        path: '/api/v1/auth/refresh',
        handler: () => {
          refreshed = true;
          return user;
        },
      },
    ]);
    renderAt('/');
    expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument();
  });
});

describe('project page', () => {
  it('lists tasks and creates one with the CSRF header', async () => {
    const tasks = [task(1), task(2, 'Write docs')];
    const { calls } = mockApi([
      ...baseRoutes,
      { method: 'GET', path: '/api/v1/users/me', body: user },
      { method: 'GET', path: '/api/v1/tasks', handler: () => ({ items: tasks, next_cursor: null }) },
      {
        method: 'POST',
        path: '/api/v1/tasks',
        status: 201,
        handler: async (req) => {
          const created = { ...task(3), title: ((await req.json()) as { title: string }).title };
          tasks.push(created);
          return created;
        },
      },
    ]);
    renderAt('/projects/WEB');
    const table = await screen.findByRole('table');
    expect(await within(table).findByText('Write docs')).toBeInTheDocument();
    expect(within(table).getAllByText('Ada Lovelace')).toHaveLength(2);

    await userEvent.type(screen.getByLabelText('New task title'), 'Ship it{Enter}');
    expect(await within(table).findByText('Ship it')).toBeInTheDocument();
    const post = calls.find((c) => c.method === 'POST' && c.url.endsWith('/api/v1/tasks'));
    expect(post?.headers.get('X-CSRF-Token')).toBe('csrf-123');
  });

  it('changes status with optimistic-concurrency version', async () => {
    const { calls } = mockApi([
      ...baseRoutes,
      { method: 'GET', path: '/api/v1/users/me', body: user },
      { method: 'GET', path: '/api/v1/tasks', body: { items: [task(1)], next_cursor: null } },
      { method: 'PATCH', path: '/api/v1/tasks/t1', body: task(1) },
    ]);
    renderAt('/projects/WEB');
    await userEvent.selectOptions(await screen.findByLabelText('Status of WEB-1'), 'Done');
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    const patch = calls.find((c) => c.method === 'PATCH')!;
    expect(await patch.json()).toEqual({ status_id: 's-done', expected_version: 1 });
  });
});

describe('theme', () => {
  it('toggles dark mode', async () => {
    mockApi([...baseRoutes, { method: 'GET', path: '/api/v1/users/me', body: user }]);
    renderAt('/');
    const button = await screen.findByRole('button', { name: 'Dark mode' });
    const before = document.documentElement.classList.contains('dark');
    await userEvent.click(button);
    expect(document.documentElement.classList.contains('dark')).toBe(!before);
  });
});
