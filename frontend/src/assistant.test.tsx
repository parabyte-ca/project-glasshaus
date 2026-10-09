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

const signedIn: Route = { method: 'GET', path: '/api/v1/users/me', body: user };
const task = (key: string, title: string, extra: object = {}) => ({
  key,
  title,
  status: 'To do',
  assignee: 'Ada Lovelace',
  due_date: '2026-10-01',
  days: null,
  ...extra,
});
const brief = {
  id: 'b1',
  kind: 'digest',
  title: 'WEB stand-up, Fri Oct 9: 1 overdue, 0 due today',
  created_at: '2026-10-09T12:00:00Z',
  project_id: 'p1',
  project_key: 'WEB',
  content: {
    date: '2026-10-09',
    since: null,
    health: 'at_risk',
    progress: 40,
    open: 3,
    done: 2,
    overdue: 1,
    completed: [],
    overdue_tasks: [task('WEB-1', 'Send <invoice>', { days: 8 })],
    due_today: [],
    due_soon: [],
    stale: [task('WEB-2', 'Stuck review', { status: 'In progress', days: 6 })],
    unassigned: [],
    warnings: [],
    stale_days: 5,
    headline: null,
    summary: 'One task is badly late.',
    focus: [{ text: 'Chase the invoice', task_key: 'WEB-1' }],
    highlights: [],
    concerns: [],
    ai_model: 'fake',
    ai_note: null,
  },
};
const status = (settings: unknown = null) => ({
  settings,
  account_name: 'Project assistant (AI)',
  can_manage: true,
  can_approve: true,
  ai: false,
  email_available: false,
  channels: [{ id: 'i1', name: '#web', kind: 'slack' }],
});

beforeEach(() => {
  document.cookie = 'gh_csrf=csrf-123; path=/';
});
afterEach(() => vi.restoreAllMocks());

describe('project assistant', () => {
  it('shows the latest digest with task links and the AI label', async () => {
    mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/projects/p1/assistant', body: { ...status(), can_manage: false } },
      {
        method: 'GET',
        path: '/api/v1/projects/p1/assistant/briefs',
        body: [{ id: 'b1', kind: 'digest', title: brief.title, created_at: brief.created_at }],
      },
      { method: 'GET', path: '/api/v1/assistant/briefs/b1', body: brief },
    ]);
    renderAt('/projects/WEB/assistant');
    const article = await screen.findByRole('article', { name: brief.title });
    expect(within(article).getByText(/Written by the project assistant \(AI\)/)).toBeInTheDocument();
    expect(within(article).getByText('One task is badly late.')).toBeInTheDocument();
    const overdue = within(article).getByRole('region', { name: 'Overdue' });
    expect(overdue).toHaveTextContent('Send <invoice>');
    expect(overdue).toHaveTextContent('8 days late');
    expect(within(overdue).getByRole('link', { name: 'WEB-1' })).toHaveAttribute(
      'href',
      '/projects/WEB?task=WEB-1',
    );
    expect(within(article).getByRole('region', { name: 'No update for 5+ days' })).toHaveTextContent(
      'Stuck review',
    );
    expect(screen.queryByRole('heading', { name: 'Assistant settings' })).not.toBeInTheDocument();
  });

  it('lets a project admin turn it on with a schedule and a Slack channel', async () => {
    let saved: unknown = null;
    const { calls } = mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/projects/p1/assistant', handler: () => status(saved) },
      { method: 'GET', path: '/api/v1/projects/p1/assistant/briefs', body: [] },
      { method: 'GET', path: '/api/v1/projects/p1/assistant/suggestions', body: [] },
      {
        method: 'PUT',
        path: '/api/v1/projects/p1/assistant',
        handler: async (req) => {
          const body = (await req.json()) as Record<string, unknown>;
          saved = {
            ...body,
            project_id: 'p1',
            next_digest_at: '2026-10-12T12:00:00Z',
            next_weekly_at: '2026-10-16T18:00:00Z',
            last_run_at: null,
            last_error: null,
          };
          return saved;
        },
      },
    ]);
    renderAt('/projects/WEB/assistant');
    await screen.findByRole('heading', { name: 'Assistant settings' });
    expect(screen.getByText(/AI write-ups are off/)).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /Email/ })).toBeDisabled();
    await userEvent.clear(screen.getByLabelText('Stale after (days without an update)'));
    await userEvent.type(screen.getByLabelText('Stale after (days without an update)'), '3');
    await userEvent.selectOptions(screen.getByLabelText('Slack or Teams (digest only)'), 'i1');
    await userEvent.click(screen.getByRole('button', { name: 'Turn on' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true));
    const put = calls.find((c) => c.method === 'PUT')!;
    const body = (await put.json()) as {
      stale_days: number;
      delivery: { channel_id: string };
      digest: { weekdays_only: boolean };
    };
    expect(body.stale_days).toBe(3);
    expect(body.delivery.channel_id).toBe('i1');
    expect(body.digest.weekdays_only).toBe(true);
    expect(await screen.findByRole('button', { name: 'Write a digest now' })).toBeInTheDocument();
  });

  it('shows the approval queue and approves an edited follow-up, keeping the mention', async () => {
    const settings = {
      enabled: true,
      timezone: 'UTC',
      digest: { enabled: true, hour: 8, minute: 0, weekdays_only: true },
      weekly: { enabled: true, weekday: 4, hour: 14 },
      stale_days: 5,
      delivery: { in_app: true, email: false, channel_id: null },
      suggestions: true,
      project_id: 'p1',
      next_digest_at: null,
      next_weekly_at: null,
      last_run_at: null,
      last_error: null,
    };
    const suggestion = {
      id: 's1',
      project_id: 'p1',
      kind: 'comment',
      source: 'rules',
      status: 'open',
      reason: '3 days overdue',
      task: {
        id: 't1',
        key: 'WEB-1',
        title: 'Send invoice',
        due_date: '2026-10-06',
        assignee: 'Ada Lovelace',
      },
      comment: '@[Ada Lovelace](user:00000000-0000-0000-0000-000000000001) this was due Oct 6. New date?',
      due_date: null,
      assignee_id: null,
      assignee: null,
      new_task: null,
      created_at: '2026-10-09T12:00:00Z',
      decided_at: null,
      decided_by: null,
      result: null,
    };
    const { calls } = mockApi([
      ...baseRoutes,
      signedIn,
      {
        method: 'GET',
        path: '/api/v1/projects/p1/assistant',
        body: { ...status(settings), can_manage: false, can_approve: true },
      },
      { method: 'GET', path: '/api/v1/projects/p1/assistant/briefs', body: [] },
      { method: 'GET', path: '/api/v1/projects/p1/assistant/suggestions', body: [suggestion] },
      {
        method: 'POST',
        path: '/api/v1/projects/p1/assistant/suggestions/s1/approve',
        body: { ...suggestion, status: 'approved', result: 'Comment posted on WEB-1' },
      },
    ]);
    renderAt('/projects/WEB/assistant');
    const queue = await screen.findByRole('region', { name: /Suggestions/ });
    const box = await within(queue).findByLabelText('Comment to @Ada Lovelace');
    expect(box).toHaveValue('this was due Oct 6. New date?');
    expect(within(queue).getByText('3 days overdue')).toBeInTheDocument();
    await userEvent.clear(box);
    await userEvent.type(box, 'Can you send it today?');
    await userEvent.click(within(queue).getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/s1/approve'))).toBe(true));
    const body = (await calls.find((c) => c.url.endsWith('/s1/approve'))!.json()) as { comment: string };
    expect(body.comment).toBe(
      '@[Ada Lovelace](user:00000000-0000-0000-0000-000000000001) Can you send it today?',
    );
    expect(await screen.findByText('Comment posted on WEB-1')).toBeInTheDocument();
  });
});
