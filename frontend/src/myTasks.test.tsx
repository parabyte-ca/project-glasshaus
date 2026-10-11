import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from './App';
import { DeviceNotifications } from './components/DeviceNotifications';
import { loadMyTasks, queuedDone, rememberUser, saveMyTasks } from './lib/offline';
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
const day = (offset: number) => {
  const d = new Date(Date.now() + offset * 86_400_000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};
const mine = [
  { ...task(1, 'Late one'), due_date: day(-2) },
  { ...task(2, 'Due today'), due_date: day(0) },
  { ...task(3, 'This week'), due_date: day(3) },
  { ...task(4, 'Someday'), due_date: null },
];

let online = true;
function goOnline(value: boolean) {
  online = value;
  window.dispatchEvent(new Event(value ? 'online' : 'offline'));
}

beforeEach(() => {
  document.cookie = 'gh_csrf=csrf-123; path=/';
  resetTaskUpdates();
  online = true;
  Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => online });
});
afterEach(() => vi.restoreAllMocks());

describe('my tasks', () => {
  it('groups open tasks by due date, asks only for mine, and ticks one done', async () => {
    const { calls } = mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/tasks', body: { items: mine, next_cursor: null } },
      {
        method: 'POST',
        path: '/api/v1/tasks/t2/complete',
        body: { ...mine[1], status: statuses[1] },
      },
    ]);
    renderAt('/my');
    const overdue = await screen.findByRole('region', { name: /Overdue/ });
    expect(within(overdue).getByText('Late one')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: /Today/ })).getByText('Due today')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /Next 7 days/ })).toHaveTextContent('This week');
    expect(screen.getByRole('region', { name: /No due date/ })).toHaveTextContent('Someday');
    const query = new URL(calls.find((c) => c.url.includes('/api/v1/tasks?'))!.url).searchParams;
    expect(query.getAll('assignee_ids')).toEqual(['u1']);
    expect(query.getAll('status_categories')).toEqual(['backlog', 'todo', 'in_progress']);
    expect(loadMyTasks('u1')?.items).toHaveLength(4); // kept for offline use

    await userEvent.click(screen.getByRole('checkbox', { name: 'Mark WEB-2 done' }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/tasks/t2/complete'))).toBe(true));
    expect(await screen.findByText('Done: WEB-2')).toBeInTheDocument();
  });

  it('removes a ticked task at once and brings it back with Undo', async () => {
    const { calls } = mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/tasks', body: { items: mine, next_cursor: null } },
      { method: 'POST', path: '/api/v1/tasks/t3/complete', body: { ...mine[2], status: statuses[1] } },
      { method: 'POST', path: '/api/v1/tasks/t3/reopen', body: mine[2] },
    ]);
    renderAt('/my');
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Mark WEB-3 done' }));
    expect(screen.queryByText('This week')).not.toBeInTheDocument();
    // The newest toast's Undo (an earlier test's toast may still be on screen).
    await userEvent.click((await screen.findAllByRole('button', { name: 'Undo' })).at(-1)!);
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/tasks/t3/reopen'))).toBe(true));
    expect(await screen.findByText('This week')).toBeInTheDocument();
    expect(await screen.findByText('WEB-3 is open again')).toBeInTheDocument();
  });

  it('opens from the copy on this device when offline and syncs ticks when back online', async () => {
    rememberUser(user as never);
    saveMyTasks('u1', mine as never);
    goOnline(false);
    const { calls } = mockApi([
      ...baseRoutes,
      { method: 'GET', path: '/api/v1/users/me', handler: () => Promise.reject(new TypeError('offline')) },
      { method: 'GET', path: '/api/v1/tasks', handler: () => Promise.reject(new TypeError('offline')) },
      { method: 'POST', path: '/api/v1/tasks/t1/complete', body: { ...mine[0], status: statuses[1] } },
    ]);
    renderAt('/my');
    expect(await screen.findByText(/You’re offline/, {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText('Late one')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('checkbox', { name: 'Mark WEB-1 done' }));
    expect(screen.queryByText('Late one')).not.toBeInTheDocument();
    expect(queuedDone('u1').map((q) => q.key)).toEqual(['WEB-1']);
    expect(calls.some((c) => c.url.endsWith('/complete'))).toBe(false);
    expect(screen.getByRole('status', { name: '' })).toHaveTextContent('(1 waiting)');

    // Back online: the server answers again and the queued tick is sent once.
    vi.restoreAllMocks();
    const back = mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/tasks', body: { items: mine.slice(1), next_cursor: null } },
      { method: 'POST', path: '/api/v1/tasks/t1/complete', body: { ...mine[0], status: statuses[1] } },
    ]);
    goOnline(true);
    expect(await screen.findByText(/Synced 1 task/, {}, { timeout: 5000 })).toBeInTheDocument();
    expect(back.calls.filter((c) => c.url.endsWith('/tasks/t1/complete'))).toHaveLength(1);
    expect(queuedDone('u1')).toEqual([]);
  }, 20_000);
});

describe('device notifications', () => {
  it('says so when the browser cannot show notifications', async () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <DeviceNotifications />
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/cannot show Glasshaus notifications/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Turn on notifications' })).not.toBeInTheDocument();
  });

  it('asks iPhone users to add the app to the Home Screen first', async () => {
    vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(
      'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1',
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <DeviceNotifications />
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/add Glasshaus to your Home Screen/)).toBeInTheDocument();
  });
});
