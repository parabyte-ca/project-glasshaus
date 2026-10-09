import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from './App';
import { resetTaskUpdates } from './lib/taskUpdates';
import { baseRoutes, mockApi, statuses, task, user, type Route } from './test/mockApi';

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
const later = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const tasks = (items: unknown[]): Route => ({
  method: 'GET',
  path: '/api/v1/tasks',
  body: { items, next_cursor: null },
});

beforeEach(() => {
  document.cookie = 'gh_csrf=csrf-123; path=/';
  resetTaskUpdates();
});
afterEach(() => vi.restoreAllMocks());

describe('pages', () => {
  it('names the tab after the page and shows Not found for unknown addresses', async () => {
    mockApi([...baseRoutes, signedIn, tasks([task(1)])]);
    renderAt('/projects/WEB');
    await screen.findByText('Task 1');
    expect(document.title).toBe('Website · Glasshaus');
    window.history.pushState({}, '', '/nowhere');
    window.dispatchEvent(new PopStateEvent('popstate'));
    expect(await screen.findByRole('heading', { name: 'Not found' })).toBeInTheDocument();
    expect(document.title).toBe('Not found · Glasshaus');
  });

  it('says a missing project was not found instead of loading forever', async () => {
    mockApi([
      {
        method: 'GET',
        path: '/api/v1/projects/by-key/GONE',
        status: 404,
        body: { title: 'Not found', status: 404, detail: 'project not found', code: 'not_found' },
      },
      ...baseRoutes,
      signedIn,
    ]);
    renderAt('/projects/GONE');
    expect(await screen.findByRole('heading', { name: 'Not found' })).toBeInTheDocument();
    expect(screen.getByText(/This project doesn't exist/)).toBeInTheDocument();
  });

  it('moves focus to the new page heading after navigating', async () => {
    mockApi([...baseRoutes, signedIn, tasks([task(1)])]);
    renderAt('/');
    await userEvent.click(await screen.findByRole('link', { name: /WEB\s*Website/ }));
    const heading = await screen.findByRole('heading', { name: /Website/, level: 1 });
    await waitFor(() => expect(heading).toHaveFocus());
  });
});

describe('project page', () => {
  it('keeps search and filters in the address', async () => {
    mockApi([...baseRoutes, signedIn, tasks([task(1)])]);
    renderAt('/projects/WEB?q=login&done=1');
    expect(await screen.findByLabelText('Search tasks')).toHaveValue('login');
    expect(screen.getByLabelText('Show completed')).toBeChecked();
    await userEvent.type(screen.getByLabelText('Search tasks'), 's');
    await userEvent.selectOptions(screen.getByLabelText('Priority filter'), 'high');
    const params = new URLSearchParams(window.location.search);
    expect(params.get('q')).toBe('logins');
    expect(params.get('priority')).toBe('high');
    expect(params.get('done')).toBe('1');
  });

  it('says it is loading instead of "No tasks match" while the list loads', async () => {
    mockApi([
      ...baseRoutes,
      signedIn,
      {
        method: 'GET',
        path: '/api/v1/tasks',
        handler: async () => {
          await later(150);
          return { items: [], next_cursor: null };
        },
      },
    ]);
    renderAt('/projects/WEB');
    expect(await screen.findByText('Loading tasks…')).toBeInTheDocument();
    expect(screen.queryByText('No tasks match.')).toBeNull();
    expect(await screen.findByText('No tasks match.')).toBeInTheDocument();
  });

  it('closing a task opened from the list goes back instead of adding a history entry', async () => {
    mockApi([
      ...baseRoutes,
      signedIn,
      tasks([task(1)]),
      { method: 'GET', path: '/api/v1/tasks/WEB-1', body: task(1) },
      { method: 'GET', path: '/api/v1/tasks/t1/comments', body: [] },
      { method: 'GET', path: '/api/v1/activity', body: { items: [], next_cursor: null } },
      { method: 'GET', path: '/api/v1/tasks/t1/dependencies', body: { predecessors: [], successors: [] } },
    ]);
    renderAt('/projects/WEB');
    const length = window.history.length;
    await userEvent.click(await screen.findByRole('button', { name: /WEB-1\s*Task 1/ }));
    await screen.findByRole('dialog');
    expect(window.history.length).toBe(length + 1);
    await userEvent.click(screen.getByRole('button', { name: 'Close task' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(window.location.search).toBe('');
  });
});

describe('board', () => {
  it('moves a card to the next column with Alt+Right and with its Move menu', async () => {
    // Like the server: a PATCH changes the task and later reads see it.
    const current = new Map([task(1), task(2)].map((t) => [t.id, t]));
    const patch = (id: string): Route => ({
      method: 'PATCH',
      path: `/api/v1/tasks/${id}`,
      handler: async (req) => {
        const body = (await req.json()) as { status_id?: string; position?: number };
        const next = {
          ...current.get(id)!,
          ...(body.status_id ? { status: statuses.find((s) => s.id === body.status_id)! } : {}),
          position: body.position ?? current.get(id)!.position,
          version: current.get(id)!.version + 1,
        };
        current.set(id, next);
        return next;
      },
    });
    const { calls } = mockApi([
      ...baseRoutes,
      signedIn,
      {
        method: 'GET',
        path: '/api/v1/tasks',
        handler: () => ({ items: [...current.values()], next_cursor: null }),
      },
      patch('t1'),
      patch('t2'),
    ]);
    renderAt('/projects/WEB?kind=board');
    const card = (await screen.findByText('Task 1')).closest('button')!;
    card.focus();
    await userEvent.keyboard('{Alt>}{ArrowRight}{/Alt}');
    await waitFor(() => expect(calls.filter((c) => c.method === 'PATCH')).toHaveLength(1));
    expect(await calls.find((c) => c.method === 'PATCH')!.json()).toEqual({
      status_id: 's-done',
      position: 1024,
      expected_version: 1,
    });
    expect(await screen.findByText('WEB-1 moved to Done, 1 of 1')).toBeInTheDocument();
    await waitFor(() =>
      expect(within(screen.getByTestId('column-Done')).getByText('Task 1').closest('button')).toHaveFocus(),
    );

    await userEvent.selectOptions(screen.getByLabelText('Move WEB-2'), 'To Done');
    await waitFor(() => expect(calls.filter((c) => c.method === 'PATCH')).toHaveLength(2));
  });
});

describe('controls', () => {
  it('tabs move with the arrow keys', async () => {
    mockApi([...baseRoutes, signedIn]);
    renderAt('/time');
    const first = await screen.findByRole('tab', { name: 'Timesheet' });
    expect(first).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Team report' })).toHaveAttribute('tabindex', '-1');
    first.focus();
    await userEvent.keyboard('{ArrowRight}');
    const second = screen.getByRole('tab', { name: 'Team report' });
    expect(second).toHaveFocus();
    expect(second).toHaveAttribute('aria-selected', 'true');
    expect(new URLSearchParams(window.location.search).get('tab')).toBe('team');
  });

  it('marks the field the server rejected', async () => {
    mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/tokens', body: [] },
      { method: 'GET', path: '/api/v1/oauth/apps', body: [] },
      {
        method: 'POST',
        path: '/api/v1/tokens',
        status: 422,
        body: {
          title: 'Invalid input',
          status: 422,
          detail: 'request validation failed',
          code: 'invalid_input',
          errors: [{ loc: ['body', 'name'], msg: 'String should have at most 100 characters', type: 'x' }],
        },
      },
    ]);
    renderAt('/account');
    const name = await screen.findByLabelText('Token name');
    await userEvent.type(name, 'x');
    await userEvent.click(screen.getByRole('button', { name: 'Create token' }));
    await waitFor(() => expect(name).toHaveAttribute('aria-invalid', 'true'));
    expect(name).toHaveAccessibleDescription('String should have at most 100 characters');
    expect(screen.getByRole('alert')).toHaveTextContent('Name: String should have at most 100 characters');
  });

  it('Escape closes the notifications list and returns focus to its button', async () => {
    mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/notifications', body: { items: [], next_cursor: null } },
    ]);
    renderAt('/');
    const bell = await screen.findByRole('button', { name: 'Notifications' });
    await userEvent.click(bell);
    const list = await screen.findByRole('region', { name: 'Notifications' });
    expect(list).toHaveFocus();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('region', { name: 'Notifications' })).toBeNull();
    expect(bell).toHaveFocus();
  });
});
