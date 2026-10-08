import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from './App';
import { baseRoutes, mockApi, project, task, user, type Route } from './test/mockApi';

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
