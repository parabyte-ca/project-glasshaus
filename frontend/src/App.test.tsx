import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from './App';
import { aiOn, baseRoutes, mockApi, project, task, user, type Route } from './test/mockApi';

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

describe('scheduling views', () => {
  const today = new Date().toISOString().slice(0, 10);
  const dated = (n: number, start: string, due: string) => ({ ...task(n), start_date: start, due_date: due });
  const scheduleRoutes = (items: unknown[]): Route[] => [
    { method: 'GET', path: '/api/v1/tasks', body: { items, next_cursor: null } },
    {
      method: 'GET',
      path: '/api/v1/projects/p1/schedule',
      body: {
        project_id: 'p1',
        project_start: today,
        project_finish: today,
        tasks: [],
        critical_path: ['t1'],
        unscheduled: [],
        dependencies: [
          {
            id: 'd1',
            project_id: 'p1',
            predecessor_id: 't1',
            predecessor_key: 'WEB-1',
            predecessor_title: 'Task 1',
            successor_id: 't2',
            successor_key: 'WEB-2',
            successor_title: 'Task 2',
            type: 'fs',
            lag_days: 0,
            created_at: today,
          },
        ],
      },
    },
    { method: 'GET', path: '/api/v1/projects/p1/baselines', body: [] },
    {
      method: 'GET',
      path: '/api/v1/projects/p1/schedule/warnings',
      body: [{ kind: 'overdue', task_id: 't2', key: 'WEB-2', message: 'WEB-2 is 3 day(s) overdue', days: 3 }],
    },
  ];

  it('timeline draws bars, highlights the critical path and moves a bar with the keyboard', async () => {
    const { calls } = mockApi([
      ...baseRoutes,
      signedIn,
      ...scheduleRoutes([
        dated(1, '2026-03-02', '2026-03-04'),
        dated(2, '2026-03-05', '2026-03-06'),
        { ...task(3), due_date: null },
      ]),
      { method: 'PATCH', path: '/api/v1/tasks/t1', body: task(1) },
      {
        method: 'POST',
        path: '/api/v1/projects/p1/reschedule',
        body: {
          executed: false,
          moves: [
            {
              task_id: 't2',
              key: 'WEB-2',
              start_date: '2026-03-05',
              due_date: '2026-03-06',
              new_start_date: '2026-03-07',
              new_due_date: '2026-03-08',
              days: 2,
            },
          ],
        },
      },
    ]);
    renderAt('/projects/WEB?kind=timeline');
    const bar = await screen.findByRole('button', {
      name: /WEB-1 Task 1, 2026-03-02 to 2026-03-04, critical/,
    });
    expect(bar).toHaveClass('fill-rose-500');
    expect(screen.getByTestId('bar-WEB-2')).toHaveClass('fill-sky-600');
    expect(screen.getByText('1 task(s) without dates are not shown.')).toBeInTheDocument();
    expect(screen.getByText('1 schedule warning(s)')).toBeInTheDocument();

    bar.focus();
    await userEvent.keyboard('{ArrowRight}');
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    expect(await calls.find((c) => c.method === 'PATCH')!.json()).toEqual({
      start_date: '2026-03-03',
      due_date: '2026-03-05',
      expected_version: 1,
    });

    await userEvent.click(screen.getByRole('button', { name: 'Check dependencies' }));
    expect(await screen.findByText('WEB-2: 2026-03-05 → 2026-03-07 (+2d)')).toBeInTheDocument();
  });

  it('calendar shows tasks on the days they span and expands busy days', async () => {
    const busy = [1, 2, 3, 4, 5, 6].map((n) => dated(n, today, today));
    mockApi([...baseRoutes, signedIn, ...scheduleRoutes(busy)]);
    renderAt('/projects/WEB?kind=calendar');
    const cell = await screen.findByRole('cell', { name: today });
    expect(await within(cell).findByRole('button', { name: 'Task 1' })).toBeInTheDocument();
    expect(within(cell).queryByRole('button', { name: 'Task 6' })).not.toBeInTheDocument();
    await userEvent.click(within(cell).getByRole('button', { name: '+2 more' }));
    expect(within(cell).getByRole('button', { name: 'Task 6' })).toBeInTheDocument();
    expect(within(cell).getByRole('button', { name: 'Show less' })).toHaveAttribute('aria-expanded', 'true');
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
      { method: 'GET', path: '/api/v1/tasks', body: { items: [task(1), task(2)], next_cursor: null } },
      { method: 'GET', path: '/api/v1/tasks/WEB-1', body: task(1) },
      { method: 'GET', path: '/api/v1/tasks/t1/comments', handler: () => comments },
      { method: 'GET', path: '/api/v1/activity', body: { items: [], next_cursor: null } },
      { method: 'GET', path: '/api/v1/tasks/t1/dependencies', body: { predecessors: [], successors: [] } },
      {
        method: 'POST',
        path: '/api/v1/dependencies',
        status: 201,
        body: { dependency: {}, rescheduled: [{ task_id: 't1', key: 'WEB-1', days: 2 }] },
      },
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

    await userEvent.selectOptions(within(dialog).getByLabelText('Waits for task'), 'WEB-2 Task 2');
    await userEvent.selectOptions(within(dialog).getByLabelText('Dependency type'), 'Start → start');
    await userEvent.clear(within(dialog).getByLabelText('Lag in days (negative for lead)'));
    await userEvent.type(within(dialog).getByLabelText('Lag in days (negative for lead)'), '-1');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add' }));
    expect(await within(dialog).findByText('Auto-scheduled: WEB-1 +2d')).toBeInTheDocument();
    const dep = calls.find((c) => c.method === 'POST' && c.url.endsWith('/api/v1/dependencies'))!;
    expect(await dep.json()).toEqual({ predecessor: 't2', successor: 't1', type: 'ss', lag_days: -1 });

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

  it('opens in-app links from report alerts and ignores others', async () => {
    const note = (id: string, title: string, link: string) => ({
      id,
      kind: 'report_alert',
      task_id: null,
      project_id: null,
      actor_id: null,
      title,
      link,
      created_at: '2026-01-01T00:00:00Z',
      read_at: '2026-01-01T00:00:00Z',
    });
    mockApi([
      ...baseRoutes,
      signedIn,
      {
        method: 'GET',
        path: '/api/v1/notifications',
        body: {
          items: [
            note('n1', 'Open work: Open is 3, above 2', '/reports/r1'),
            note('n2', 'Elsewhere', '//evil.example/x'),
          ],
          next_cursor: null,
        },
      },
      { method: 'GET', path: '/api/v1/reports/r1', status: 404, body: { detail: 'report not found' } },
    ]);
    renderAt('/');
    await userEvent.click(await screen.findByRole('button', { name: /Notifications/ }));
    await userEvent.click(await screen.findByText('Elsewhere'));
    expect(window.location.pathname).toBe('/');
    await userEvent.click(await screen.findByRole('button', { name: /Notifications/ }));
    await userEvent.click(await screen.findByText('Open work: Open is 3, above 2'));
    await waitFor(() => expect(window.location.pathname).toBe('/reports/r1'));
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

describe('about and privacy', () => {
  it('links the source code and lists third-party licences', async () => {
    mockApi([
      ...baseRoutes,
      signedIn,
      {
        method: 'GET',
        path: '/api/v1/licenses',
        body: [{ name: 'FastAPI', version: '1.0', license: 'MIT' }],
      },
      { method: 'GET', path: '/licenses.json', body: [{ name: 'react', version: '19.0.0', license: 'MIT' }] },
    ]);
    renderAt('/about');
    expect(await screen.findByRole('heading', { name: 'About and privacy', level: 1 })).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Source code for this server' })).toHaveAttribute(
      'href',
      'https://github.com/parabyte-ca/project-glasshaus',
    );
    expect(await screen.findByText(/FastAPI 1.0/)).toBeInTheDocument();
    expect(await screen.findByText(/react 19.0.0/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'About, privacy and source code' })).toBeInTheDocument();
  });

  it('lets people download their own data', async () => {
    mockApi([...baseRoutes, signedIn]);
    renderAt('/account');
    expect(await screen.findByRole('link', { name: 'Download my data' })).toHaveAttribute(
      'href',
      '/api/v1/users/me/export',
    );
  });
});

describe('connected access', () => {
  it('approves an MCP client with fewer permissions', async () => {
    const { calls } = mockApi([
      signedIn,
      {
        method: 'GET',
        path: '/api/v1/oauth/requests/req-1',
        body: {
          id: 'req-1',
          client_name: 'Visual Studio Code',
          client_id: 'c1',
          redirect_host: '127.0.0.1:33418',
          scopes: ['read', 'tasks:write'],
          scope_labels: { read: 'Read things', 'tasks:write': 'Change tasks' },
          expires_at: '2026-10-08T13:00:00Z',
        },
      },
      {
        method: 'POST',
        path: '/api/v1/oauth/requests/req-1',
        body: { redirect_to: 'http://127.0.0.1:33418/callback?code=abc' },
      },
    ]);
    vi.spyOn(console, 'error').mockImplementation(() => {}); // jsdom cannot navigate away
    renderAt('/oauth/consent?request=req-1');
    expect(
      await screen.findByRole('heading', { name: 'Allow Visual Studio Code to use your account?' }),
    ).toBeInTheDocument();
    expect(screen.getByText('127.0.0.1:33418')).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText(/tasks:write/));
    await userEvent.click(screen.getByRole('button', { name: 'Allow' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true));
    const post = calls.find((c) => c.method === 'POST')!;
    expect(post.headers.get('X-CSRF-Token')).toBe('csrf-123');
    expect(await post.json()).toEqual({ approve: true, scopes: ['read'] });
  });

  it('creates an API token, shows it once and disconnects an app', async () => {
    const created = {
      id: 't1',
      name: 'VS Code',
      prefix: 'ghp_abcd',
      scopes: ['read', 'tasks:write', 'projects:write'],
      created_at: '2026-10-08T00:00:00Z',
      expires_at: '2027-01-06T00:00:00Z',
      last_used_at: null,
      revoked_at: null,
    };
    let tokens: unknown[] = [];
    let apps = [
      {
        id: 'a1',
        client_id: 'c1',
        client_name: 'Claude',
        scopes: ['read'],
        created_at: '2026-10-01T00:00:00Z',
        last_used_at: null,
      },
    ];
    const { calls } = mockApi([
      ...baseRoutes.filter((r) => !['/api/v1/tokens', '/api/v1/oauth/apps'].includes(String(r.path))),
      signedIn,
      { method: 'GET', path: '/api/v1/tokens', handler: () => tokens },
      {
        method: 'POST',
        path: '/api/v1/tokens',
        status: 201,
        handler: () => {
          tokens = [created];
          return { ...created, token: 'ghp_abcd_secret' };
        },
      },
      { method: 'GET', path: '/api/v1/oauth/apps', handler: () => apps },
      {
        method: 'DELETE',
        path: '/api/v1/oauth/apps/a1',
        status: 204,
        handler: () => {
          apps = [];
        },
      },
    ]);
    renderAt('/account');
    await userEvent.type(await screen.findByLabelText('Token name'), 'VS Code');
    await userEvent.click(screen.getByRole('button', { name: 'Create token' }));
    expect(await screen.findByText('ghp_abcd_secret')).toBeInTheDocument();
    const post = calls.find((c) => c.method === 'POST')!;
    expect(await post.json()).toEqual({
      name: 'VS Code',
      scopes: ['read', 'tasks:write', 'projects:write'],
      expires_in_days: 90,
    });
    expect(await screen.findByRole('button', { name: 'Revoke VS Code' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Disconnect Claude' }));
    const ask = await screen.findByRole('dialog', { name: 'Disconnect Claude?' });
    expect(within(ask).getByText('It loses access to your account now.')).toBeInTheDocument();
    await userEvent.click(within(ask).getByRole('button', { name: 'Disconnect' }));
    expect(await screen.findByText(/No apps are connected/)).toBeInTheDocument();
  });
});

describe('administration', () => {
  const member = { ...user, id: 'u2', email: 'lin@example.com', name: 'Lin', org_role: 'member' };

  it('shows backup health and the last restore drill', async () => {
    mockApi([
      {
        method: 'GET',
        path: '/api/v1/admin/backups',
        body: {
          available: true,
          folder: '/backups',
          interval_hours: 24,
          drill_days: 7,
          count: 2,
          total_bytes: 3 * 1024 * 1024,
          latest: [
            {
              name: 'glasshaus-20261009T020000Z.dump',
              bytes: 2 * 1024 * 1024,
              created_at: '2026-10-09T02:00:00Z',
            },
            {
              name: 'glasshaus-20261008T020000Z.dump',
              bytes: 1024 * 1024,
              created_at: '2026-10-08T02:00:00Z',
            },
          ],
          drill: {
            finished_at: '2026-10-09T02:01:00Z',
            ok: false,
            dump: 'glasshaus-20261009T020000Z.dump',
            dump_bytes: 2097152,
            seconds: 4,
            tables: 61,
            revision: 'a',
            live_revision: 'a',
            rows: { users: 3, projects: 2, tasks: 40 },
            error: 'pg_restore failed',
          },
          problems: [{ code: 'drill_failed', message: 'The last restore drill failed: pg_restore failed' }],
        },
      },
      ...baseRoutes,
      signedIn,
    ]);
    renderAt('/admin?tab=backups');
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The last restore drill failed: pg_restore failed',
    );
    expect(
      screen.getByText(/^Failed .* 61 tables, 3 people, 2 projects, 40 tasks, 4 s$/),
    ).toBeInTheDocument();
    const files = screen.getByRole('table', { name: 'Newest backups' });
    expect(within(files).getAllByRole('row')).toHaveLength(3);
    expect(within(files).getByText('2.0 MB')).toBeInTheDocument();
  });

  it('connects a Slack command and schedules a channel post', async () => {
    const integration = (over: object) => ({
      id: 'i1',
      kind: 'slack',
      name: '#web',
      enabled: true,
      project_id: null,
      events: [],
      url_host: 'hooks.slack.com',
      secret_set: true,
      inbound_url: null,
      email: null,
      last_success_at: null,
      last_error: null,
      last_error_at: null,
      created_at: '2026-10-09T00:00:00Z',
      ...over,
    });
    const { calls } = mockApi([
      ...baseRoutes,
      signedIn,
      {
        method: 'GET',
        path: '/api/v1/integrations',
        body: [
          integration({}),
          integration({
            id: 'i2',
            kind: 'slack_command',
            name: 'Slack',
            inbound_url: 'https://pm.example.com/api/v1/integrations/i2/slack',
          }),
        ],
      },
      { method: 'GET', path: '/api/v1/integrations/event-types', body: ['task.created'] },
      { method: 'POST', path: '/api/v1/integrations', status: 201, body: integration({ id: 'i3' }) },
      { method: 'GET', path: '/api/v1/integrations/i1/posts', body: [] },
      {
        method: 'GET',
        path: '/api/v1/reports',
        body: [{ id: 'r1', name: 'Open work', owner_id: 'u1', description: '', shared: false }],
      },
      { method: 'POST', path: '/api/v1/integrations/i1/posts', status: 201, body: {} },
    ]);
    renderAt('/admin?tab=integrations');
    expect(
      await screen.findByText('https://pm.example.com/api/v1/integrations/i2/slack'),
    ).toBeInTheDocument();
    expect(screen.getByText(/Request URL/)).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText('Type'), 'Slack command (/glasshaus)');
    expect(screen.queryByLabelText('Project (optional)')).toBeNull(); // the whole organization
    await userEvent.type(screen.getByLabelText('Name'), 'Slack');
    await userEvent.type(screen.getByLabelText('Signing secret'), 'sig');
    await userEvent.type(screen.getByLabelText('Bot token (xoxb-…)'), 'xoxb-1');
    await userEvent.click(screen.getByRole('button', { name: 'Connect' }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/integrations'))).toBe(true),
    );
    const created = calls.find((c) => c.method === 'POST' && c.url.endsWith('/integrations'))!;
    expect(await created.json()).toMatchObject({
      kind: 'slack_command',
      secret: 'sig',
      token: 'xoxb-1',
      project_id: null,
    });

    await userEvent.click(screen.getByRole('button', { name: 'Scheduled posts' }));
    const panel = (await screen.findByRole('heading', { name: 'Scheduled posts to #web' })).closest(
      'section',
    )!;
    await userEvent.selectOptions(within(panel).getByLabelText('Report'), 'Open work');
    await userEvent.click(within(panel).getByRole('button', { name: 'Add post' }));
    await waitFor(() =>
      expect(calls.some((c) => c.url.endsWith('/integrations/i1/posts') && c.method === 'POST')).toBe(true),
    );
    const post = calls.find((c) => c.url.endsWith('/integrations/i1/posts') && c.method === 'POST')!;
    expect(await post.json()).toMatchObject({
      kind: 'report',
      report_id: 'r1',
      schedule: { frequency: 'weekly', weekday: 0, hour: 9 },
    });
  });

  it('deactivates a person after confirming', async () => {
    let people = [user, member];
    const { calls } = mockApi([
      ...baseRoutes.filter((r) => r.path !== '/api/v1/users'),
      signedIn,
      { method: 'GET', path: '/api/v1/users', handler: () => people },
      {
        method: 'PATCH',
        path: '/api/v1/users/u2',
        handler: () => {
          people = [user, { ...member, is_active: false }];
          return people[1];
        },
      },
    ]);
    renderAt('/admin');
    await userEvent.click(await screen.findByRole('button', { name: 'Deactivate Lin' }));
    // Cancel first: nothing changes, and focus goes back to the button.
    const ask = await screen.findByRole('dialog', { name: 'Deactivate Lin?' });
    expect(within(ask).getByRole('button', { name: 'Cancel' })).toHaveFocus();
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Deactivate Lin' })).toHaveFocus();
    expect(calls.some((c) => c.method === 'PATCH')).toBe(false);
    await userEvent.click(screen.getByRole('button', { name: 'Deactivate Lin' }));
    await userEvent.click(
      within(await screen.findByRole('dialog', { name: 'Deactivate Lin?' })).getByRole('button', {
        name: 'Deactivate',
      }),
    );
    expect(await screen.findByRole('button', { name: 'Reactivate Lin' })).toBeInTheDocument();
    const patch = calls.find((c) => c.method === 'PATCH')!;
    expect(await patch.json()).toEqual({ is_active: false });
    expect(screen.queryByRole('button', { name: `Deactivate ${user.name}` })).not.toBeInTheDocument();
  });

  it('erases a person only after their email is typed', async () => {
    let people: object[] = [user, member];
    const { calls } = mockApi([
      ...baseRoutes.filter((r) => r.path !== '/api/v1/users'),
      signedIn,
      { method: 'GET', path: '/api/v1/users', handler: () => people },
      {
        method: 'POST',
        path: '/api/v1/admin/users/u2/erase',
        handler: () => {
          people = [user, { ...member, name: 'Former user 0a1b2c', erased_at: '2026-10-10T00:00:00Z' }];
          return { user_id: 'u2', name: 'Former user 0a1b2c', removed: { sessions: 1 } };
        },
      },
    ]);
    renderAt('/admin');
    expect(await screen.findByRole('link', { name: 'Download Lin’s data' })).toHaveAttribute(
      'href',
      '/api/v1/admin/users/u2/export',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Erase Lin' }));
    const confirmButton = screen.getAllByRole('button', { name: 'Erase Lin' }).at(-1)!;
    expect(confirmButton).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Type lin@example.com to confirm'), 'LIN@example.com');
    expect(confirmButton).toBeEnabled();
    await userEvent.click(confirmButton);
    expect(
      await screen.findByText(/Lin was erased and is now shown as “Former user 0a1b2c”/),
    ).toBeInTheDocument();
    const post = calls.find((c) => c.method === 'POST' && c.url.endsWith('/erase'))!;
    expect(await post.json()).toEqual({ confirm_email: 'LIN@example.com' });
    expect(await screen.findByText('Erased')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Erase Former user 0a1b2c' })).not.toBeInTheDocument();
  });

  it('checks the audit log seal', async () => {
    mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/audit-log', body: [] },
      {
        method: 'POST',
        path: '/api/v1/audit-log/verify',
        body: {
          ok: false,
          entries: 12,
          first_seq: 1,
          last_seq: 13,
          head: 'ab'.repeat(32),
          starts_after_purge: false,
          problems: [
            {
              seq: 7,
              id: 'e7',
              created_at: '2026-10-09T02:00:00Z',
              problem: 'changed after it was recorded',
            },
          ],
        },
      },
    ]);
    renderAt('/admin?tab=audit');
    await userEvent.click(await screen.findByRole('button', { name: 'Check integrity' }));
    expect(await screen.findByText('1 problem found:')).toBeInTheDocument();
    expect(screen.getByText(/Entry 7 .*: changed after it was recorded/)).toBeInTheDocument();
    expect(screen.getByText('ab'.repeat(32))).toBeInTheDocument();
  });

  it('connects a signed webhook and shows the secret once', async () => {
    let integrations: unknown[] = [];
    const { calls } = mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/integrations', handler: () => integrations },
      { method: 'GET', path: '/api/v1/integrations/event-types', body: ['task.created', 'task.completed'] },
      {
        method: 'POST',
        path: '/api/v1/integrations',
        status: 201,
        handler: () => {
          const created = {
            id: 'i1',
            kind: 'webhook',
            name: 'CI',
            enabled: true,
            project_id: null,
            events: ['task.created'],
            url_host: 'ci.example.com',
            secret_set: true,
            inbound_url: null,
            email: null,
            last_success_at: null,
            last_error: null,
            last_error_at: null,
            created_at: '2026-10-08T00:00:00Z',
          };
          integrations = [created];
          return { ...created, signing_secret: 'sig-secret-123' };
        },
      },
    ]);
    renderAt('/admin?tab=integrations');
    await userEvent.selectOptions(await screen.findByLabelText('Type'), 'webhook');
    await userEvent.type(screen.getByLabelText('Name'), 'CI');
    await userEvent.type(screen.getByLabelText('Webhook URL'), 'https://ci.example.com/hook');
    await userEvent.click(await screen.findByLabelText('task.completed'));
    await userEvent.click(screen.getByRole('button', { name: 'Connect' }));
    expect(await screen.findByText('sig-secret-123')).toBeInTheDocument();
    expect(await screen.findByRole('cell', { name: 'CI' })).toBeInTheDocument();
    const post = calls.find((c) => c.method === 'POST')!;
    expect(await post.json()).toMatchObject({
      kind: 'webhook',
      url: 'https://ci.example.com/hook',
      events: ['task.created', 'comment.created'],
    });
  });

  it('is hidden from members', async () => {
    mockApi([...baseRoutes, { method: 'GET', path: '/api/v1/users/me', body: member }]);
    renderAt('/admin');
    expect(await screen.findByRole('alert')).toHaveTextContent('owners and admins');
    expect(screen.queryByRole('link', { name: 'Admin' })).not.toBeInTheDocument();
  });
});

describe('single sign-on', () => {
  it('offers identity providers and explains failures', async () => {
    mockApi([
      { method: 'GET', path: '/api/v1/users/me', status: 401, body: { detail: 'no session' } },
      { method: 'POST', path: '/api/v1/auth/refresh', status: 401, body: { detail: 'no session' } },
      {
        method: 'GET',
        path: '/api/v1/auth/sso/providers',
        body: [
          {
            name: 'Company login',
            slug: 'corp',
            kind: 'oidc',
            start_url: '/api/v1/auth/sso/default/corp/start',
          },
        ],
      },
    ]);
    renderAt('/projects/WEB?sso_error=your%20email%20domain%20is%20not%20allowed');
    const link = await screen.findByRole('link', { name: 'Sign in with Company login' });
    expect(link).toHaveAttribute('href', '/api/v1/auth/sso/default/corp/start?next=%2Fprojects%2FWEB');
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Single sign-on failed: your email domain is not allowed',
    );
  });

  it('creates a private calendar link', async () => {
    const { calls } = mockApi([
      ...baseRoutes,
      signedIn,
      {
        method: 'POST',
        path: '/api/v1/calendar-feed',
        body: {
          url: 'http://localhost/api/v1/calendar/ghc_abc.ics',
          created_at: '2026-10-08T00:00:00Z',
          last_used_at: null,
        },
      },
    ]);
    renderAt('/account');
    await userEvent.click(await screen.findByRole('button', { name: 'Create calendar link' }));
    expect(await screen.findByText('http://localhost/api/v1/calendar/ghc_abc.ics')).toBeInTheDocument();
    expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/api/v1/calendar-feed'))).toBe(true);
  });

  it('links single sign-on from Account', async () => {
    mockApi([
      ...baseRoutes.filter((r) => r.path !== '/api/v1/auth/sso/identities'),
      signedIn,
      {
        method: 'GET',
        path: '/api/v1/auth/sso/identities',
        body: [
          {
            provider_name: 'Entra ID',
            provider_slug: 'entra',
            kind: 'oidc',
            linked: false,
            linked_at: null,
            last_login_at: null,
            link_url: '/api/v1/auth/sso/default/entra/start?link=true',
          },
        ],
      },
    ]);
    renderAt('/account?sso_linked=1');
    const link = await screen.findByRole('link', { name: 'Link Entra ID' });
    expect(link).toHaveAttribute('href', '/api/v1/auth/sso/default/entra/start?link=true&csrf=csrf-123');
    expect(screen.getByText('Single sign-on linked.')).toBeInTheDocument();
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

describe('automations', () => {
  const rule = {
    id: 'r1',
    project_id: 'p1',
    name: 'Ship it',
    enabled: true,
    trigger: { type: 'status_changed', to_category: 'done' },
    conditions: [],
    actions: [{ type: 'add_tags', tags: ['shipped'] }],
    run_on_automation: false,
    created_by: 'u1',
    webhook_secret: 'abc',
    last_run_at: null,
    next_run_at: null,
    created_at: '2026-01-01T00:00:00Z',
  };

  it('builds a rule, dry-runs it and retries a failed run', async () => {
    let created: unknown;
    const { calls } = mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/projects/p1/automation-rules', handler: () => (created ? [rule] : []) },
      {
        method: 'GET',
        path: '/api/v1/projects/p1/automation-runs',
        body: [
          {
            id: 'run1',
            rule_id: 'r1',
            rule_name: 'Ship it',
            task_id: 't1',
            trigger_type: 'status_changed',
            status: 'failed',
            error: 'https://hooks.example.com: HTTP 503',
            results: { task_key: 'WEB-1', phase: 'webhooks' },
            attempts: 1,
            started_at: '2026-01-02T00:00:00Z',
            finished_at: '2026-01-02T00:00:01Z',
          },
        ],
      },
      {
        method: 'POST',
        path: '/api/v1/projects/p1/automation-rules/test',
        body: { matched: true, conditions: [], planned_actions: ["add_tags: add tags ['shipped']"] },
      },
      {
        method: 'POST',
        path: '/api/v1/projects/p1/automation-rules',
        status: 201,
        handler: async (req) => {
          created = await req.json();
          return rule;
        },
      },
      { method: 'POST', path: '/api/v1/automation-runs/run1/retry', body: {} },
    ]);
    renderAt('/projects/WEB/settings?tab=automations');
    await userEvent.click(await screen.findByRole('button', { name: 'New rule' }));
    const form = screen.getByRole('form', { name: 'New rule' });
    await userEvent.type(within(form).getByLabelText('Rule name'), 'Ship it');
    await userEvent.type(within(form).getByLabelText('Tags (comma separated)'), 'shipped, done');
    await userEvent.click(within(form).getByRole('button', { name: 'Add condition' }));
    await userEvent.selectOptions(within(form).getByLabelText('Operator'), 'in');
    const value = within(form).getByLabelText('Value');
    await userEvent.clear(value);
    await userEvent.type(value, 'high, urgent');
    await userEvent.type(within(form).getByLabelText('Test against task (e.g. WEB-12)'), 'WEB-1');
    await userEvent.click(within(form).getByRole('button', { name: 'Dry run' }));
    expect(await within(form).findByText('Conditions match — it would:')).toBeInTheDocument();
    await userEvent.click(within(form).getByRole('button', { name: 'Create rule' }));
    await waitFor(() =>
      expect(created).toEqual({
        name: 'Ship it',
        trigger: { type: 'status_changed', to_category: 'done' },
        conditions: [{ field: 'priority', op: 'in', value: ['high', 'urgent'] }],
        actions: [{ type: 'add_tags', tags: ['shipped', 'done'] }],
      }),
    );
    expect(await screen.findByText('Ship it', { selector: 'span' })).toBeInTheDocument();
    expect(screen.getByText(/Status changed → done/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Retry run of Ship it' }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/automation-runs/run1/retry'))).toBe(true));
  });

  it('creates a project from a template', async () => {
    const { calls } = mockApi([
      ...baseRoutes.filter((r) => r.path !== '/api/v1/project-templates'),
      signedIn,
      {
        method: 'GET',
        path: '/api/v1/project-templates',
        body: [
          {
            id: 'tpl1',
            name: 'Launch',
            description: '',
            created_by: 'u1',
            created_at: '2026-01-01T00:00:00Z',
            summary: { statuses: 5, fields: 1, views: 0, tasks: 12, dependencies: 2, rules: 1, recurring: 0 },
          },
        ],
      },
      {
        method: 'POST',
        path: '/api/v1/project-templates/tpl1/instantiate',
        status: 201,
        handler: async (req) => {
          expect(await req.json()).toEqual({ workspace_id: 'w1', key: 'WEB', name: 'Website' });
          return project;
        },
      },
      { method: 'GET', path: /\/api\/v1\/tasks$/, body: { items: [], next_cursor: null } },
    ]);
    renderAt('/');
    await userEvent.type(await screen.findByLabelText('Key'), 'web');
    await userEvent.type(screen.getByLabelText('Name'), 'Website');
    await userEvent.selectOptions(await screen.findByLabelText('Start from'), 'tpl1');
    await userEvent.click(screen.getByRole('button', { name: 'Create project' }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/tpl1/instantiate'))).toBe(true));
  });
});

describe('time tracking and goals', () => {
  it('logs time from the task drawer', async () => {
    let logged: unknown;
    mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/tasks', body: { items: [task(1)], next_cursor: null } },
      { method: 'GET', path: '/api/v1/tasks/WEB-1', body: task(1) },
      { method: 'GET', path: '/api/v1/tasks/t1/comments', body: [] },
      { method: 'GET', path: '/api/v1/activity', body: { items: [], next_cursor: null } },
      { method: 'GET', path: '/api/v1/tasks/t1/dependencies', body: { predecessors: [], successors: [] } },
      {
        method: 'POST',
        path: '/api/v1/time-entries',
        status: 201,
        handler: async (req) => {
          logged = await req.json();
          return {};
        },
      },
    ]);
    renderAt('/projects/WEB?task=WEB-1');
    const duration = await screen.findByLabelText('Duration');
    await userEvent.type(duration, 'soon');
    await userEvent.click(screen.getByRole('button', { name: 'Log time' }));
    expect(await screen.findByText(/Enter a duration like/)).toBeInTheDocument();
    await userEvent.clear(duration);
    await userEvent.type(duration, '1h 15m');
    await userEvent.type(screen.getByLabelText('Note'), 'review');
    await userEvent.click(screen.getByRole('button', { name: 'Log time' }));
    await waitFor(() => expect(logged).toEqual({ task: 't1', minutes: 75, note: 'review' }));
  });

  it('stops a running timer from the task drawer', async () => {
    let running = true;
    const { calls } = mockApi([
      ...baseRoutes.filter((r) => r.path !== '/api/v1/timer'),
      signedIn,
      {
        method: 'GET',
        path: '/api/v1/timer',
        handler: () =>
          running
            ? {
                task_id: 't1',
                task_key: 'WEB-1',
                task_title: 'Task 1',
                started_at: new Date().toISOString(),
                note: '',
                elapsed_seconds: 5,
              }
            : null,
      },
      {
        method: 'POST',
        path: '/api/v1/timer/stop',
        handler: () => {
          running = false;
          return {};
        },
      },
      { method: 'GET', path: '/api/v1/tasks', body: { items: [task(1)], next_cursor: null } },
      { method: 'GET', path: '/api/v1/tasks/WEB-1', body: task(1) },
      { method: 'GET', path: '/api/v1/tasks/t1/comments', body: [] },
      { method: 'GET', path: '/api/v1/activity', body: { items: [], next_cursor: null } },
      { method: 'GET', path: '/api/v1/tasks/t1/dependencies', body: { predecessors: [], successors: [] } },
    ]);
    renderAt('/projects/WEB?task=WEB-1');
    await userEvent.click(await screen.findByRole('button', { name: 'Stop timer on WEB-1' }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/api/v1/timer/stop'))).toBe(true));
    expect(await screen.findByRole('button', { name: 'Start timer on WEB-1' })).toBeInTheDocument();
  });

  it('shows a weekly timesheet with totals', async () => {
    mockApi([
      ...baseRoutes,
      signedIn,
      {
        method: 'GET',
        path: '/api/v1/timesheets',
        handler: (req) => {
          const from = new URL(req.url).searchParams.get('date_from')!;
          const days = Array.from({ length: 7 }, (_, i) => {
            const d = new Date(`${from}T00:00:00Z`);
            d.setUTCDate(d.getUTCDate() + i);
            return d.toISOString().slice(0, 10);
          });
          return {
            user_id: 'u1',
            date_from: days[0],
            date_to: days[6],
            days,
            rows: [
              {
                project_id: 'p1',
                project_key: 'WEB',
                project_name: 'Website',
                task_id: 't1',
                task_key: 'WEB-1',
                task_title: 'Fix login',
                minutes_by_day: { [days[0]!]: 90, [days[2]!]: 30 },
                total: 120,
              },
            ],
            totals_by_day: { [days[0]!]: 90, [days[2]!]: 30 },
            total: 120,
            billable_total: 30,
          };
        },
      },
    ]);
    renderAt('/time');
    const table = await screen.findByRole('table', { name: /Timesheet/ });
    expect(within(table).getByText('Fix login')).toBeInTheDocument();
    expect(within(table).getAllByText('1.5')).toHaveLength(2);
    expect(screen.getByText('2h this week, 30m billable.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Export CSV' }).getAttribute('href')).toMatch(
      /^\/api\/v1\/time-entries\/export\?user_id=u1&date_from=/,
    );
  });

  it('creates an objective with a task-based key result', async () => {
    let created: unknown;
    mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/objectives', body: [] },
      {
        method: 'POST',
        path: '/api/v1/objectives',
        status: 201,
        handler: async (req) => {
          created = await req.json();
          return {};
        },
      },
    ]);
    renderAt('/goals');
    await userEvent.click(await screen.findByRole('button', { name: 'New objective' }));
    const form = screen.getByRole('form', { name: 'New objective' });
    await userEvent.type(within(form).getByLabelText('Objective'), 'Relaunch the site');
    await userEvent.type(within(form).getByLabelText('Key result'), 'Launch tasks done');
    await userEvent.selectOptions(within(form).getByLabelText('Measured by'), 'tasks');
    await userEvent.selectOptions(await within(form).findByLabelText('Project'), 'p1');
    await userEvent.click(within(form).getByRole('button', { name: 'Create objective' }));
    await waitFor(() =>
      expect(created).toMatchObject({
        title: 'Relaunch the site',
        key_results: [{ title: 'Launch tasks done', kind: 'tasks', project_id: 'p1' }],
      }),
    );
    expect((created as { period: string }).period).toMatch(/^\d{4}-Q[1-4]$/);
  });
});

describe('keyboard and command palette', () => {
  it('opens with Ctrl+K, finds a task and opens it', async () => {
    mockApi([
      ...baseRoutes,
      signedIn,
      {
        method: 'GET',
        path: '/api/v1/tasks',
        handler: (req) =>
          new URL(req.url).searchParams.get('q') === 'docs'
            ? { items: [task(2, 'Write docs')], next_cursor: null }
            : { items: [], next_cursor: null },
      },
      { method: 'GET', path: '/api/v1/tasks/WEB-2', body: task(2, 'Write docs') },
    ]);
    renderAt('/');
    await screen.findByRole('heading', { name: 'Projects', level: 1 });
    await userEvent.keyboard('{Control>}k{/Control}');
    const dialog = await screen.findByRole('dialog', { name: 'Command palette' });
    const input = within(dialog).getByRole('combobox');
    expect(input).toHaveFocus();
    await userEvent.type(input, 'docs');
    expect(await within(dialog).findByRole('option', { name: /WEB-2 Write docs/ })).toBeInTheDocument();
    await userEvent.keyboard('{Enter}');
    await waitFor(() => expect(window.location.search).toBe('?task=WEB-2'));
    expect(window.location.pathname).toBe('/projects/WEB');
    expect(screen.queryByRole('dialog', { name: 'Command palette' })).not.toBeInTheDocument();
  });

  it('navigates with g-sequences, lists shortcuts with ? and focuses project search with /', async () => {
    mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/tasks', body: { items: [], next_cursor: null } },
    ]);
    renderAt('/projects/WEB');
    const search = await screen.findByLabelText('Search tasks');
    await userEvent.keyboard('/');
    expect(search).toHaveFocus();
    search.blur();
    await userEvent.keyboard('?');
    const help = await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
    expect(within(help).getByText('Go to Workload')).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await userEvent.keyboard('gw');
    await waitFor(() => expect(window.location.pathname).toBe('/workload'));
  });

  it('asks the assistant in plain words', async () => {
    const { calls } = mockApi([
      ...baseRoutes.filter((r) => r.path !== '/api/v1/ai/status'),
      aiOn,
      signedIn,
      { method: 'GET', path: '/api/v1/tasks', body: { items: [], next_cursor: null } },
      {
        method: 'POST',
        path: '/api/v1/ai/search',
        body: {
          query: 'my late work',
          filters: { explanation: 'Your overdue tasks' },
          task_query: {},
          items: [task(7, 'Renew certificate')],
          usage: { provider: 'fake', model: 'fake', input_tokens: 0, output_tokens: 0, duration_ms: 1 },
        },
      },
    ]);
    renderAt('/');
    await screen.findByRole('heading', { name: 'Projects', level: 1 });
    await userEvent.click(screen.getByRole('button', { name: /Search/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Command palette' });
    await userEvent.type(within(dialog).getByRole('combobox'), 'my late work');
    await userEvent.click(within(dialog).getByRole('option', { name: /Ask: “my late work”/ }));
    expect(await within(dialog).findByText(/Your overdue tasks · 1 found/)).toBeInTheDocument();
    expect(within(dialog).getByRole('option', { name: /WEB-7 Renew certificate/ })).toBeInTheDocument();
    const post = calls.find((c) => c.url.endsWith('/api/v1/ai/search'))!;
    expect(await post.json()).toEqual({ query: 'my late work', limit: 20 });
  });

  it('hands a report question to the Reports page', async () => {
    mockApi([
      ...baseRoutes.filter((r) => r.path !== '/api/v1/ai/status'),
      { ...aiOn, body: { ...(aiOn.body as object), features: ['reports'] } },
      signedIn,
      { method: 'GET', path: '/api/v1/tasks', body: { items: [], next_cursor: null } },
      { method: 'GET', path: '/api/v1/reports', body: [] },
      { method: 'POST', path: '/api/v1/ai/reports', status: 503, body: { detail: 'busy' } },
    ]);
    renderAt('/');
    await screen.findByRole('heading', { name: 'Projects', level: 1 });
    await userEvent.click(screen.getByRole('button', { name: /Search/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Command palette' });
    await userEvent.type(within(dialog).getByRole('combobox'), 'who is overdue');
    expect(within(dialog).queryByRole('option', { name: /^Ask: / })).toBeNull();
    await userEvent.click(within(dialog).getByRole('option', { name: /Ask reports: “who is overdue”/ }));
    await waitFor(() => expect(window.location.pathname).toBe('/reports'));
    expect(new URLSearchParams(window.location.search).get('ask')).toBe('who is overdue');
    expect(await screen.findByLabelText('Question')).toHaveValue('who is overdue');
  });
});

describe('AI assistant', () => {
  it('stays hidden when the assistant is off', async () => {
    mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/tasks', body: { items: [], next_cursor: null } },
    ]);
    renderAt('/projects/WEB');
    await screen.findByLabelText('New task title');
    expect(screen.queryByRole('button', { name: 'Assistant' })).not.toBeInTheDocument();
  });

  it('drafts tasks and adds the chosen ones', async () => {
    const { calls } = mockApi([
      ...baseRoutes.filter((r) => r.path !== '/api/v1/ai/status'),
      aiOn,
      signedIn,
      { method: 'GET', path: '/api/v1/tasks', body: { items: [], next_cursor: null } },
      {
        method: 'POST',
        path: '/api/v1/ai/projects/p1/draft-tasks',
        body: {
          project_key: 'WEB',
          drafts: [
            {
              title: 'Pick a host',
              description: 'Compare two',
              priority: 'high',
              estimate_minutes: 120,
              tags: ['infra'],
            },
            { title: 'Move DNS', description: '', priority: 'none', estimate_minutes: null, tags: [] },
          ],
          usage: { provider: 'fake', model: 'fake', input_tokens: 0, output_tokens: 0, duration_ms: 1 },
        },
      },
      { method: 'POST', path: '/api/v1/tasks', status: 201, body: task(9) },
    ]);
    renderAt('/projects/WEB');
    await userEvent.click(await screen.findByRole('button', { name: 'Assistant' }));
    await userEvent.click(await screen.findByRole('tab', { name: 'Draft tasks' }));
    await userEvent.type(screen.getByLabelText('What needs doing?'), 'Move hosting');
    await userEvent.click(screen.getByRole('button', { name: 'Draft tasks' }));
    expect(await screen.findByText('Pick a host')).toBeInTheDocument();
    expect(screen.getByText(/Written by AI/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Add task: Pick a host' }));
    expect(await screen.findByText('Added')).toBeInTheDocument();
    const created = calls.filter((c) => c.method === 'POST' && c.url.endsWith('/api/v1/tasks'));
    expect(created).toHaveLength(1);
    expect(await created[0]!.json()).toEqual({
      project_id: 'p1',
      title: 'Pick a host',
      description: 'Compare two',
      priority: 'high',
      estimate_minutes: 120,
      tags: ['infra'],
    });
  });

  it('lets admins turn it on', async () => {
    const settings = {
      audit_retention_days: 365,
      activity_retention_days: 0,
      notification_retention_days: 90,
      deleted_task_retention_days: 30,
      ai_enabled: false,
      ai_features: ['summaries', 'drafting', 'risks', 'search'],
      assistant_trusted: [],
    };
    const { calls } = mockApi([
      ...baseRoutes.filter((r) => r.path !== '/api/v1/ai/status'),
      {
        ...aiOn,
        body: {
          available: true,
          enabled: false,
          provider: 'anthropic',
          model: 'claude-opus-5-5',
          features: [],
        },
      },
      signedIn,
      { method: 'GET', path: '/api/v1/admin/settings', body: settings },
      {
        method: 'PATCH',
        path: '/api/v1/admin/settings',
        handler: async (req) => ({ ...settings, ...((await req.json()) as object) }),
      },
    ]);
    renderAt('/admin?tab=ai');
    expect(await screen.findByText('claude-opus-5-5')).toBeInTheDocument();
    await userEvent.click(await screen.findByLabelText('Turn on the AI assistant for this organization'));
    await userEvent.click(screen.getByLabelText(/Risk flags/));
    await userEvent.click(screen.getByRole('button', { name: 'Save AI settings' }));
    expect(await screen.findByText('Saved')).toBeInTheDocument();
    const patch = calls.find((c) => c.method === 'PATCH')!;
    expect(await patch.json()).toEqual({
      ai_enabled: true,
      ai_features: ['summaries', 'drafting', 'search'],
      assistant_trusted: [],
    });
  });

  it('keeps the AI switch and features when saving without a provider', async () => {
    const settings = {
      audit_retention_days: 365,
      activity_retention_days: 0,
      notification_retention_days: 90,
      deleted_task_retention_days: 30,
      ai_enabled: true,
      ai_features: ['summaries', 'search'],
      assistant_trusted: [],
      manager_visibility: 'shared',
    };
    const { calls } = mockApi([
      ...baseRoutes.filter((r) => r.path !== '/api/v1/ai/status'),
      {
        ...aiOn,
        body: { available: false, enabled: true, provider: null, model: null, features: [] },
      },
      signedIn,
      { method: 'GET', path: '/api/v1/admin/settings', body: settings },
      {
        method: 'PATCH',
        path: '/api/v1/admin/settings',
        handler: async (req) => ({ ...settings, ...((await req.json()) as object) }),
      },
    ]);
    renderAt('/admin?tab=ai');
    await userEvent.click(await screen.findByRole('button', { name: 'Save AI settings' }));
    const patch = calls.find((c) => c.method === 'PATCH')!;
    expect(await patch.json()).toEqual({ assistant_trusted: [] }); // nothing else is touched
  });
});
