import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
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

const manager: Route = { method: 'GET', path: '/api/v1/users/me', body: { ...user, direct_reports: 1 } };
const task = (title: string, extra: object = {}) => ({
  id: `t-${title}`,
  key: 'WEB-7',
  title,
  project_key: 'WEB',
  project_name: 'Website',
  status: 'To do',
  category: 'todo',
  priority: 'high',
  due_date: '2026-10-01',
  updated_at: '2026-10-01T00:00:00Z',
  completed_at: null,
  ...extra,
});
const grace = {
  id: 'u2',
  name: 'Grace Hopper',
  email: 'grace@example.com',
  job_title: 'Engineer',
  department: 'R&D',
  manager_id: 'u1',
  level: 1,
  open: 4,
  in_progress: 1,
  overdue: 2,
  due_this_week: 1,
  logged_this_week: 450,
  logged_last_week: 1200,
  capacity_week: 2400,
  completed_last_7_days: 3,
  stale: 0,
  recent: [task('Ship release', { completed_at: '2026-10-08T10:00:00Z' })],
  projects: [
    { id: 'p1', key: 'WEB', name: 'Website', health: 'at_risk', open_tasks: 3, visible: true },
    { id: 'p9', key: null, name: null, health: 'on_track', open_tasks: 1, visible: false },
  ],
};

beforeEach(() => {
  document.cookie = 'gh_csrf=csrf-123; path=/';
});
afterEach(() => vi.restoreAllMocks());

describe('My team', () => {
  it('is in the menu for managers and shows each report’s work, time and projects', async () => {
    const { calls } = mockApi([
      ...baseRoutes,
      manager,
      {
        method: 'GET',
        path: '/api/v1/team',
        body: { visibility: 'shared', direct_reports: 1, people: [grace] },
      },
      {
        method: 'GET',
        path: '/api/v1/team/u2/tasks',
        body: { person: 'u2', hidden: 1, tasks: [task('Fix login')] },
      },
    ]);
    renderAt('/team');
    expect(await screen.findByRole('link', { name: 'My team' })).toHaveAttribute('href', '/team');
    const card = (await screen.findByRole('heading', { name: 'Grace Hopper' })).closest('li')!;
    expect(card).toHaveTextContent('Engineer · R&D');
    expect(within(card).getByText('Overdue').nextSibling).toHaveTextContent('2');
    expect(card).toHaveTextContent('7.5 / 40h');
    expect(within(card).getByRole('link', { name: 'Website' })).toHaveAttribute('href', '/projects/WEB');
    expect(card).toHaveTextContent('A project you can’t open');
    expect(card).toHaveTextContent('Ship release');
    expect(screen.getByText(/counts only/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('checkbox', { name: /Include everyone below me/ }));
    expect(calls.some((c) => c.url.includes('everyone=true'))).toBe(true);

    await userEvent.click(await screen.findByRole('button', { name: "See Grace Hopper's tasks" }));
    const dialog = await screen.findByRole('dialog', { name: /Grace Hopper: open work/ });
    expect(await within(dialog).findByRole('link', { name: 'Fix login' })).toHaveAttribute(
      'href',
      '/projects/WEB?task=t-Fix login',
    );
    expect(dialog).toHaveTextContent('1 more in projects you can’t open.');
  });

  it('is on the home page and in the command palette, next to each project assistant', async () => {
    mockApi([
      ...baseRoutes,
      manager,
      { method: 'GET', path: '/api/v1/tasks', body: { items: [], next_cursor: null } },
    ]);
    renderAt('/');
    await screen.findByRole('heading', { name: 'Projects', level: 1 });
    const home = screen.getByRole('main');
    expect(within(home).getByRole('link', { name: 'My team' })).toHaveAttribute('href', '/team');
    await userEvent.keyboard('{Control>}k{/Control}');
    const dialog = await screen.findByRole('dialog', { name: 'Command palette' });
    await userEvent.type(within(dialog).getByRole('combobox'), 'team');
    expect(await within(dialog).findByRole('option', { name: /My team/ })).toBeInTheDocument();
    await userEvent.clear(within(dialog).getByRole('combobox'));
    await userEvent.type(within(dialog).getByRole('combobox'), 'assistant');
    expect(
      await within(dialog).findByRole('option', { name: /Website: project assistant/ }),
    ).toBeInTheDocument();
  });

  it('is not in the menu for people without reports', async () => {
    mockApi([...baseRoutes, { method: 'GET', path: '/api/v1/users/me', body: user }]);
    renderAt('/my');
    await screen.findByRole('heading', { name: 'My tasks' });
    expect(screen.queryByRole('link', { name: 'My team' })).not.toBeInTheDocument();
  });
});
