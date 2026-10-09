import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from './App';
import { resetTaskUpdates } from './lib/taskUpdates';
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
const patches = (calls: Request[]) => calls.filter((c) => c.method === 'PATCH');

type TaskFixture = Omit<ReturnType<typeof task>, 'start_date' | 'due_date'> & {
  start_date: string | null;
  due_date: string | null;
};

const later = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** A PATCH handler that behaves like the server: applies the body and bumps the version. */
function server(initial: TaskFixture, delayMs = 0) {
  let current: TaskFixture = { ...initial };
  return {
    get: () => current,
    route: {
      method: 'PATCH',
      path: `/api/v1/tasks/${initial.id}`,
      handler: async (req: Request) => {
        const { expected_version, ...patch } = (await req.json()) as { expected_version: number };
        await later(delayMs);
        if (expected_version !== current.version) throw new Error(`stale version ${expected_version}`);
        current = { ...current, ...patch, version: current.version + 1 };
        return current;
      },
    } satisfies Route,
  };
}

const drawerRoutes = (t: TaskFixture, latest = () => t): Route[] => [
  { method: 'GET', path: '/api/v1/tasks', handler: () => ({ items: [latest()], next_cursor: null }) },
  { method: 'GET', path: '/api/v1/tasks/WEB-1', handler: latest },
  { method: 'GET', path: '/api/v1/tasks/t1/comments', body: [] },
  { method: 'GET', path: '/api/v1/activity', body: { items: [], next_cursor: null } },
  { method: 'GET', path: '/api/v1/tasks/t1/dependencies', body: { predecessors: [], successors: [] } },
];

beforeEach(() => {
  document.cookie = 'gh_csrf=csrf-123; path=/';
  resetTaskUpdates();
});
afterEach(() => vi.restoreAllMocks());

describe('switching projects', () => {
  it('starts each project with empty search and a blank new-task box', async () => {
    const ops = { ...project, id: 'p2', key: 'OPS', name: 'Operations' };
    mockApi([
      ...baseRoutes.filter((r) => r.path !== '/api/v1/projects'),
      signedIn,
      { method: 'GET', path: '/api/v1/projects', body: [project, ops] },
      { method: 'GET', path: '/api/v1/projects/by-key/OPS', body: ops },
      { method: 'GET', path: '/api/v1/projects/p2/fields', body: [] },
      { method: 'GET', path: '/api/v1/projects/p2/views', body: [] },
      { method: 'GET', path: '/api/v1/tasks', body: { items: [], next_cursor: null } },
    ]);
    renderAt('/projects/WEB');
    await userEvent.type(await screen.findByLabelText('New task title'), 'Half typed');
    await userEvent.type(screen.getByLabelText('Search tasks'), 'login');
    await userEvent.click(screen.getByRole('link', { name: /OPS\s*Operations/ }));
    expect(await screen.findByRole('heading', { name: /Operations/ })).toBeInTheDocument();
    expect(screen.getByLabelText('New task title')).toHaveValue('');
    expect(screen.getByLabelText('Search tasks')).toHaveValue('');
  });
});

describe('quick successive edits', () => {
  it('moves a timeline bar twice: shown at once, sent in order with fresh versions', async () => {
    const t = { ...task(1), start_date: '2026-03-02', due_date: '2026-03-04' };
    const api = server(t, 100); // slower than the key presses
    const { calls } = mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/tasks', handler: () => ({ items: [api.get()], next_cursor: null }) },
      {
        method: 'GET',
        path: '/api/v1/projects/p1/schedule',
        body: { tasks: [], critical_path: [], dependencies: [], unscheduled: [] },
      },
      { method: 'GET', path: '/api/v1/projects/p1/baselines', body: [] },
      { method: 'GET', path: '/api/v1/projects/p1/schedule/warnings', body: [] },
      api.route,
    ]);
    renderAt('/projects/WEB?kind=timeline');
    const bar = await screen.findByRole('button', { name: /WEB-1 Task 1, 2026-03-02 to 2026-03-04/ });
    bar.focus();
    await userEvent.keyboard('{ArrowRight}');
    // The bar moves before the server answers, so the second press builds on the first.
    await userEvent.keyboard('{ArrowRight}');
    await waitFor(() => expect(patches(calls)).toHaveLength(2));
    const bodies = await Promise.all(patches(calls).map((c) => c.json()));
    expect(bodies).toEqual([
      { start_date: '2026-03-03', due_date: '2026-03-05', expected_version: 1 },
      { start_date: '2026-03-04', due_date: '2026-03-06', expected_version: 2 },
    ]);
    expect(await screen.findByRole('button', { name: /2026-03-04 to 2026-03-06/ })).toBeInTheDocument();
  });

  it('puts a refused change back', async () => {
    mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/tasks', body: { items: [task(1)], next_cursor: null } },
      {
        method: 'PATCH',
        path: '/api/v1/tasks/t1',
        status: 409,
        handler: async () => {
          await later(100);
          return {
            type: 'about:blank',
            title: 'Conflict',
            status: 409,
            detail: 'the task changed',
            code: 'conflict',
          };
        },
      },
    ]);
    renderAt('/projects/WEB?kind=table');
    const status = await screen.findByLabelText('Status of WEB-1');
    await userEvent.selectOptions(status, 'Done');
    await waitFor(() => expect(screen.getByLabelText('Status of WEB-1')).toHaveValue('s-done')); // before the answer
    expect(await screen.findByText('the task changed')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText('Status of WEB-1')).toHaveValue('s-todo'));
  });
});

describe('task drawer edits', () => {
  it('saves a date only when it is complete and sensible', async () => {
    const api = server(task(1));
    const { calls } = mockApi([...baseRoutes, signedIn, ...drawerRoutes(task(1), api.get), api.route]);
    renderAt('/projects/WEB?task=WEB-1');
    const due = await within(await screen.findByRole('dialog')).findByLabelText('Due');
    // Typing a year passes through 0002, 0020, 0202: none of these is sent.
    fireEvent.change(due, { target: { value: '0002-02-01' } });
    fireEvent.change(due, { target: { value: '0202-02-01' } });
    expect(patches(calls)).toHaveLength(0);
    fireEvent.blur(due);
    expect(due).toHaveValue('2026-02-01'); // not a sensible year: the saved date comes back
    expect(patches(calls)).toHaveLength(0);
    fireEvent.change(due, { target: { value: '2026-03-15' } });
    fireEvent.keyDown(due, { key: 'Enter' });
    await waitFor(() => expect(patches(calls)).toHaveLength(1));
    expect(await patches(calls)[0]!.json()).toEqual({ due_date: '2026-03-15', expected_version: 1 });
  });

  it('saves an edited title on Enter and on Escape, and asks before dropping a comment', async () => {
    const api = server(task(1));
    const { calls } = mockApi([...baseRoutes, signedIn, ...drawerRoutes(task(1), api.get), api.route]);
    renderAt('/projects/WEB?task=WEB-1');
    const dialog = await screen.findByRole('dialog');
    const title = await within(dialog).findByLabelText('Title');
    await userEvent.clear(title);
    await userEvent.type(title, 'Renamed{Enter}');
    await waitFor(() => expect(patches(calls)).toHaveLength(1));
    expect(await patches(calls)[0]!.json()).toEqual({ title: 'Renamed', expected_version: 1 });

    await userEvent.type(within(dialog).getByLabelText('Title'), ' again');
    await userEvent.type(within(dialog).getByLabelText('Add a comment'), 'half a thought');
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await userEvent.click(within(dialog).getByLabelText('Title'));
    await userEvent.keyboard('{Escape}');
    // The title was saved on the way out; the comment kept the drawer open.
    await waitFor(() => expect(patches(calls)).toHaveLength(2));
    expect(await patches(calls)[1]!.json()).toEqual({ title: 'Renamed again', expected_version: 2 });
    expect(confirm).toHaveBeenCalledWith('Discard your unsent comment?');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    confirm.mockReturnValue(true);
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('closes only the command palette when it is open over the drawer', async () => {
    mockApi([...baseRoutes, signedIn, ...drawerRoutes(task(1))]);
    renderAt('/projects/WEB?task=WEB-1');
    await screen.findByRole('dialog');
    await userEvent.keyboard('{Control>}k{/Control}');
    expect(await screen.findByRole('dialog', { name: 'Command palette' })).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'Command palette' })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('keeps a comment that failed to send', async () => {
    mockApi([
      ...baseRoutes,
      signedIn,
      ...drawerRoutes(task(1)),
      {
        method: 'POST',
        path: '/api/v1/tasks/t1/comments',
        status: 503,
        body: {
          type: 'about:blank',
          title: 'Unavailable',
          status: 503,
          detail: 'try again',
          code: 'unavailable',
        },
      },
    ]);
    renderAt('/projects/WEB?task=WEB-1');
    const dialog = await screen.findByRole('dialog');
    const box = await within(dialog).findByLabelText('Add a comment');
    await userEvent.type(box, 'Important finding');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Comment' }));
    expect(await within(dialog).findByText('try again')).toBeInTheDocument();
    expect(box).toHaveValue('Important finding');
  });
});

describe('automation editor', () => {
  it('shows the right values after removing a condition', async () => {
    mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/projects/p1/automation-rules', body: [] },
      { method: 'GET', path: '/api/v1/projects/p1/automation-runs', body: [] },
    ]);
    renderAt('/projects/WEB/settings?tab=automations');
    await userEvent.click(await screen.findByRole('button', { name: 'New rule' }));
    const form = screen.getByRole('form', { name: 'New rule' });
    for (const words of ['high, urgent', 'low']) {
      await userEvent.click(within(form).getByRole('button', { name: 'Add condition' }));
      const operators = within(form).getAllByLabelText('Operator');
      await userEvent.selectOptions(operators[operators.length - 1]!, 'in');
      const values = within(form).getAllByLabelText('Value');
      const value = values[values.length - 1]!;
      await userEvent.clear(value);
      await userEvent.type(value, words);
    }
    await userEvent.click(within(form).getByRole('button', { name: 'Remove condition 1' }));
    expect(
      within(form)
        .getAllByLabelText('Value')
        .map((v) => (v as HTMLInputElement).value),
    ).toEqual(['low']);
  });
});
