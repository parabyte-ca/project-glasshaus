import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from './App';
import { baseRoutes, mockApi, task, user, type Route } from './test/mockApi';

function renderAt(path: string) {
  window.history.pushState({}, '', path);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

const signedIn: Route = { method: 'GET', path: '/api/v1/users/me', body: user };

beforeEach(() => {
  document.cookie = 'gh_csrf=csrf-123; path=/';
});
afterEach(() => vi.restoreAllMocks());

describe('authentication', () => {
  it('shows the login form, signs in and lands on the project list', async () => {
    let authed = false;
    const { calls } = mockApi([
      ...baseRoutes,
      {
        method: 'GET',
        path: '/api/v1/users/me',
        handler: () => (authed ? user : undefined),
        get status() {
          return authed ? 200 : 401;
        },
      },
      { method: 'POST', path: '/api/v1/auth/refresh', status: 401, body: { detail: 'no session' } },
      {
        method: 'POST',
        path: '/api/v1/auth/login',
        handler: async (req) => {
          authed = true;
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

describe('project views', () => {
  it('list view shows tasks and creates one with the CSRF header', async () => {
    const tasks = [task(1), task(2, 'Write docs')];
    const { calls } = mockApi([
      ...baseRoutes,
      signedIn,
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
    expect(await screen.findByText('Write docs')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('New task title'), 'Ship it{Enter}');
    expect(await screen.findByText('Ship it')).toBeInTheDocument();
    const post = calls.find((c) => c.method === 'POST' && c.url.endsWith('/api/v1/tasks'));
    expect(post?.headers.get('X-CSRF-Token')).toBe('csrf-123');
    const list = calls.find((c) => c.method === 'GET' && c.url.includes('/api/v1/tasks?'))!;
    expect(new URL(list.url).searchParams.getAll('status_categories')).toEqual([
      'backlog',
      'todo',
      'in_progress',
    ]);
  });

  it('table view shows custom fields and changes status with the task version', async () => {
    const { calls } = mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/tasks', body: { items: [task(1)], next_cursor: null } },
      { method: 'PATCH', path: '/api/v1/tasks/t1', body: task(1) },
    ]);
    renderAt('/projects/WEB?kind=table');
    await userEvent.selectOptions(await screen.findByLabelText('Status of WEB-1'), 'Done');
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    expect(await calls.find((c) => c.method === 'PATCH')!.json()).toEqual({
      status_id: 's-done',
      expected_version: 1,
    });
  });

  it('board view moves a card to another column by drag and drop', async () => {
    const { calls } = mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/tasks', body: { items: [task(1), task(2)], next_cursor: null } },
      { method: 'PATCH', path: '/api/v1/tasks/t1', body: task(1) },
    ]);
    renderAt('/projects/WEB?kind=board');
    const card = (await screen.findByText('Task 1')).closest('button')!;
    const store = new Map<string, string>();
    const dataTransfer = {
      setData: (k: string, v: string) => store.set(k, v),
      getData: (k: string) => store.get(k) ?? '',
      effectAllowed: '',
    };
    const list = calls.find((c) => c.method === 'GET' && c.url.includes('/api/v1/tasks?'))!;
    expect(new URL(list.url).searchParams.getAll('status_categories')).toEqual([]); // boards show every status
    fireEvent.dragStart(card, { dataTransfer });
    fireEvent.drop(screen.getByTestId('column-Done'), { dataTransfer });
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    expect(await calls.find((c) => c.method === 'PATCH')!.json()).toEqual({
      status_id: 's-done',
      position: 1024,
      expected_version: 1,
    });
  });
});

describe('task drawer', () => {
  it('shows comments and posts one with an @mention token', async () => {
    const comments: unknown[] = [
      {
        id: 'c1',
        task_id: 't1',
        author_id: 'u1',
        body: 'Looks **good**',
        mentions: [],
        created_at: '2026-01-01T00:00:00Z',
        edited_at: null,
      },
    ];
    const { calls } = mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/tasks', body: { items: [task(1)], next_cursor: null } },
      { method: 'GET', path: '/api/v1/tasks/WEB-1', body: task(1) },
      { method: 'GET', path: '/api/v1/tasks/t1/comments', handler: () => comments },
      { method: 'GET', path: '/api/v1/activity', body: { items: [], next_cursor: null } },
      {
        method: 'POST',
        path: '/api/v1/tasks/t1/comments',
        status: 201,
        handler: async (req) => {
          const c = {
            ...(comments[0] as object),
            id: 'c2',
            body: ((await req.json()) as { body: string }).body,
          };
          comments.push(c);
          return c;
        },
      },
    ]);
    renderAt('/projects/WEB?task=WEB-1');
    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText('good')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('Severity')).toHaveValue('s1');

    const box = within(dialog).getByLabelText('Add a comment');
    await userEvent.type(box, 'ping @ada');
    await userEvent.keyboard('{Enter}');
    await userEvent.type(box, 'please review');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Comment' }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/comments'))).toBe(true),
    );
    const post = calls.find((c) => c.method === 'POST' && c.url.endsWith('/comments'))!;
    expect(await post.json()).toEqual({ body: 'ping @[Ada Lovelace](user:u1) please review' });

    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });
});

describe('notifications', () => {
  it('shows the unread count and marks all read', async () => {
    const { calls } = mockApi([
      ...baseRoutes.filter((r) => r.path !== '/api/v1/notifications/unread-count'),
      signedIn,
      { method: 'GET', path: '/api/v1/notifications/unread-count', body: { unread: 2 } },
      {
        method: 'GET',
        path: '/api/v1/notifications',
        body: {
          items: [
            {
              id: 'n1',
              kind: 'mention',
              task_id: 't1',
              project_id: 'p1',
              actor_id: 'u2',
              title: 'You were mentioned on Task 1',
              created_at: '2026-01-01T00:00:00Z',
              read_at: null,
            },
          ],
          next_cursor: null,
        },
      },
      { method: 'POST', path: '/api/v1/notifications/read', body: { updated: 2 } },
    ]);
    renderAt('/');
    await userEvent.click(await screen.findByRole('button', { name: /Notifications.*2 unread/ }));
    expect(await screen.findByText('You were mentioned on Task 1')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Mark all read' }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/api/v1/notifications/read'))).toBe(true));
  });
});

describe('account', () => {
  it('validates, changes the password and returns to sign-in', async () => {
    let authed = true;
    const { calls } = mockApi([
      ...baseRoutes,
      {
        method: 'GET',
        path: '/api/v1/users/me',
        handler: () => (authed ? user : { detail: 'signed out' }),
        get status() {
          return authed ? 200 : 401;
        },
      },
      { method: 'POST', path: '/api/v1/auth/refresh', status: 401, body: { detail: 'no session' } },
      {
        method: 'POST',
        path: '/api/v1/auth/password',
        status: 204,
        handler: () => {
          authed = false;
        },
      },
    ]);
    renderAt('/');
    await userEvent.click(await screen.findByRole('link', { name: 'Account settings for Ada Lovelace' }));
    await userEvent.type(await screen.findByLabelText('Current password'), 'old-password-123');
    await userEvent.type(screen.getByLabelText('New password'), 'new-password-456');
    await userEvent.type(screen.getByLabelText('Confirm new password'), 'new-password-999');
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('do not match');
    expect(calls.some((c) => c.url.endsWith('/api/v1/auth/password'))).toBe(false);

    await userEvent.clear(screen.getByLabelText('Confirm new password'));
    await userEvent.type(screen.getByLabelText('Confirm new password'), 'new-password-456');
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }));
    expect(await screen.findByText('Password changed. Sign in with your new password.')).toBeInTheDocument();
    const post = calls.find((c) => c.url.endsWith('/api/v1/auth/password'))!;
    expect(post.headers.get('X-CSRF-Token')).toBe('csrf-123');
    expect(await post.json()).toEqual({
      current_password: 'old-password-123',
      new_password: 'new-password-456',
    });
  });

  it('shows the server error when the current password is wrong', async () => {
    mockApi([
      ...baseRoutes,
      signedIn,
      {
        method: 'POST',
        path: '/api/v1/auth/password',
        status: 422,
        body: { detail: 'current password is incorrect', code: 'invalid_input' },
      },
    ]);
    renderAt('/account');
    await userEvent.type(await screen.findByLabelText('Current password'), 'wrong-password-1');
    await userEvent.type(screen.getByLabelText('New password'), 'new-password-456');
    await userEvent.type(screen.getByLabelText('Confirm new password'), 'new-password-456');
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('current password is incorrect');
  });
});

describe('theme', () => {
  it('toggles dark mode', async () => {
    mockApi([...baseRoutes, signedIn]);
    renderAt('/');
    const button = await screen.findByRole('button', { name: 'Dark mode' });
    const before = document.documentElement.classList.contains('dark');
    await userEvent.click(button);
    expect(document.documentElement.classList.contains('dark')).toBe(!before);
  });
});
