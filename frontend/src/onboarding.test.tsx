import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Onboarding } from './api/client';
import App from './App';
import { baseRoutes, mockApi, onboardingDone, task, user, type Route } from './test/mockApi';

function renderAt(path: string) {
  window.history.pushState({}, '', path);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

type State = Onboarding;

/** Onboarding routes backed by an in-memory state, like the server: PATCH merges and is echoed. */
function onboardingServer(initial: Partial<State>) {
  let state: State = { ...onboardingDone(), ...initial } as State;
  const patches: Record<string, unknown>[] = [];
  const routes: Route[] = [
    { method: 'GET', path: '/api/v1/users/me/onboarding', handler: () => state },
    {
      method: 'PATCH',
      path: '/api/v1/users/me/onboarding',
      handler: async (req) => {
        const body = (await req.json()) as Record<string, string>;
        patches.push(body);
        state = {
          ...state,
          ...(body.tour ? { tour: body.tour } : {}),
          ...(body.checklist ? { checklist: body.checklist } : {}),
          dismissed_tips: body.dismiss_tip
            ? [...state.dismissed_tips, body.dismiss_tip]
            : state.dismissed_tips,
        } as State;
        return state;
      },
    },
  ];
  return { routes, patches };
}

const signedIn: Route = { method: 'GET', path: '/api/v1/users/me', body: user };
const projectRoutes: Route[] = [
  { method: 'GET', path: '/api/v1/tasks', body: { items: [task(1)], next_cursor: null } },
];
// Server routes first so they win over the defaults in baseRoutes.
const routes = (extra: Route[]) => [...extra, ...baseRoutes, signedIn, ...projectRoutes];

beforeAll(() => {
  // jsdom has no layout; driver.js scrolls the highlighted element into view.
  Element.prototype.scrollIntoView = vi.fn();
  // The tour follows prefers-reduced-motion; tests run without animation.
  window.matchMedia = vi.fn((query: string) => ({
    matches: query.includes('reduced-motion'),
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia;
});
beforeEach(() => {
  document.cookie = 'gh_csrf=csrf-123; path=/';
});
afterEach(() => {
  document.querySelectorAll('.driver-popover, .driver-overlay').forEach((n) => n.remove());
  vi.restoreAllMocks();
});

describe('getting-started checklist', () => {
  it('shows progress, minimizes to a pill and can be dismissed for good', async () => {
    const server = onboardingServer({
      tour: null,
      checklist: 'open',
      milestones: { created_work: true, added_collaborator: false, set_due_date: true, toured: false },
    });
    mockApi(routes(server.routes));
    renderAt('/');
    const panel = await screen.findByRole('region', { name: 'Getting started' });
    const bar = within(panel).getByRole('progressbar', { name: 'Getting started progress' });
    expect(bar).toHaveAttribute('aria-valuenow', '50');
    expect(bar).toHaveAttribute('aria-valuetext', '2 of 4 done');
    expect(within(panel).getByText('50% complete')).toBeInTheDocument();
    expect(within(panel).getByText(/Create your first project or task/)).toHaveTextContent('(done)');
    expect(within(panel).getByRole('link', { name: 'Take the product tour' })).toHaveAttribute(
      'href',
      '/projects/WEB?tour=1',
    );

    await userEvent.click(within(panel).getByRole('button', { name: 'Minimize' }));
    const pill = await screen.findByRole('button', { name: 'Getting started · 2/4' });
    expect(server.patches).toEqual([{ checklist: 'minimized' }]);
    await userEvent.click(pill);
    await userEvent.click(
      within(await screen.findByRole('region', { name: 'Getting started' })).getByRole('button', {
        name: 'Dismiss',
      }),
    );
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Getting started' })).toBeNull());
    expect(server.patches.at(-1)).toEqual({ checklist: 'dismissed' });
  });
});

describe('product tour', () => {
  it('starts on the first project visit, moves with the keyboard and records a skip', async () => {
    const server = onboardingServer({ tour: null });
    mockApi(routes(server.routes));
    renderAt('/projects/WEB');
    const card = await screen.findByRole('dialog', { name: 'Create a task' });
    expect(card).toHaveAttribute('aria-modal', 'true');
    expect(within(card).getByText('Step 1 of 4')).toBeInTheDocument();
    expect(within(card).getByRole('button', { name: 'Skip tour' })).toBeInTheDocument();

    await userEvent.keyboard('{ArrowRight}');
    expect(await screen.findByRole('dialog', { name: 'Your tasks' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Next/ }));
    expect(await screen.findByRole('dialog', { name: 'Timeline' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Back/ }));
    expect(await screen.findByRole('dialog', { name: 'Your tasks' })).toBeInTheDocument();

    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(server.patches).toEqual([{ tour: 'skipped' }]));
    expect(screen.queryByRole('dialog', { name: /Your tasks/ })).toBeNull();
  });

  it('can be restarted from Help and records a finished tour', async () => {
    const server = onboardingServer({ tour: 'completed' });
    mockApi(routes(server.routes));
    renderAt('/projects/WEB');
    await screen.findByText('Task 1');
    expect(screen.queryByRole('dialog', { name: 'Create a task' })).toBeNull(); // not again by itself
    await userEvent.click(screen.getByRole('button', { name: 'Product tour' }));
    await screen.findByRole('dialog', { name: 'Create a task' });
    for (let i = 0; i < 3; i++) await userEvent.click(screen.getByRole('button', { name: /Next/ }));
    const last = await screen.findByRole('dialog', { name: 'People' });
    expect(within(last).queryByRole('button', { name: 'Skip tour' })).toBeNull();
    await userEvent.click(within(last).getByRole('button', { name: /Done/ }));
    await waitFor(() => expect(server.patches).toEqual([{ tour: 'completed' }]));
  });
});

describe('feature tips', () => {
  it('shows beacons after a skipped tour and hides one for good', async () => {
    const server = onboardingServer({ tour: 'skipped', dismissed_tips: ['automations'] });
    mockApi(routes(server.routes));
    renderAt('/projects/WEB');
    const beacon = await screen.findByRole('button', { name: 'Tip: Timeline view' });
    expect(screen.queryByRole('button', { name: 'Tip: Automations' })).toBeNull(); // dismissed before
    await userEvent.click(beacon);
    expect(beacon).toHaveAttribute('aria-expanded', 'true');
    const tip = screen.getByRole('dialog', { name: 'Timeline view' });
    await userEvent.keyboard('{Escape}');
    expect(tip).not.toBeInTheDocument();
    await userEvent.click(beacon);
    await userEvent.click(within(screen.getByRole('dialog', { name: 'Timeline view' })).getByText('Got it'));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Tip: Timeline view' })).toBeNull());
    expect(server.patches).toEqual([{ dismiss_tip: 'timeline' }]);
  });

  it('are hidden when the tour was finished', async () => {
    mockApi(routes(onboardingServer({ tour: 'completed' }).routes));
    renderAt('/projects/WEB');
    await screen.findByText('Task 1');
    expect(screen.queryByRole('button', { name: /^Tip:/ })).toBeNull();
  });
});

describe('project people', () => {
  it('lists members and lets a project admin add a teammate', async () => {
    const ada = { ...user, id: 'u2', name: 'Grace Hopper', email: 'grace@example.com' };
    const members = [{ user_id: 'u1', role: 'admin' }];
    const { calls } = mockApi([
      { method: 'GET', path: '/api/v1/users', body: [user, ada] },
      { method: 'GET', path: '/api/v1/projects/p1/members', handler: () => members },
      {
        method: 'PUT',
        path: '/api/v1/projects/p1/members',
        handler: async (req) => {
          const body = (await req.json()) as { user_id: string; role: string };
          members.push(body);
          return body;
        },
      },
      ...routes(onboardingServer({}).routes), // the specific routes above win (first match)
    ]);
    renderAt('/projects/WEB');
    await userEvent.click(await screen.findByRole('button', { name: /People \(1\)/ }));
    const panel = screen.getByRole('region', { name: 'Project people' });
    expect(within(panel).getByText('Ada Lovelace')).toBeInTheDocument();
    await userEvent.selectOptions(within(panel).getByLabelText('Person to add'), 'Grace Hopper');
    await userEvent.selectOptions(within(panel).getByLabelText('Role'), 'Viewer');
    await userEvent.click(within(panel).getByRole('button', { name: 'Add' }));
    expect(await within(panel).findByText('Grace Hopper')).toBeInTheDocument();
    const put = calls.find((c) => c.method === 'PUT')!;
    expect(await put.json()).toEqual({ user_id: 'u2', role: 'viewer' });
  });
});
