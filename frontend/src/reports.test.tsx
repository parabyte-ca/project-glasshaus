import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ReportResult, SavedReport } from './api/client';
import App from './App';
import { ReportView } from './components/ReportView';
import { resultToCsv } from './lib/reportMeta';
import { aiOn, baseRoutes, mockApi, user, type Route } from './test/mockApi';

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

function result(overrides: Partial<ReportResult> = {}): ReportResult {
  return {
    columns: [
      { key: 'priority', label: 'Priority', kind: 'dimension', unit: 'text' },
      { key: 'count', label: 'Tasks', kind: 'measure', unit: 'count' },
      { key: 'estimate_hours', label: 'Estimate (h)', kind: 'measure', unit: 'hours' },
    ],
    rows: [
      { keys: ['high'], labels: ['High'], values: [2, 1.5] },
      { keys: ['low'], labels: ['Low'], values: [1, 0] },
    ],
    totals: [3, 1.5],
    total_groups: 2,
    truncated: false,
    date_from: null,
    date_to: null,
    generated_at: '2026-10-09T00:00:00Z',
    ...overrides,
  };
}

const saved: SavedReport = {
  id: 'r1',
  owner_id: 'u1',
  name: 'Open work',
  description: '',
  shared: false,
  definition: {
    source: 'tasks',
    group_by: [],
    measures: ['open'],
    filters: {
      project_ids: [],
      status_categories: [],
      priorities: [],
      people: [],
      tags: [],
      billable: null,
      date: null,
    },
    chart: 'kpi',
    sort: { by: 'label', descending: false },
    limit: 50,
  },
  created_at: '2026-10-09T00:00:00Z',
  updated_at: '2026-10-09T00:00:00Z',
};

beforeEach(() => {
  document.cookie = 'gh_csrf=csrf-123; path=/';
});
afterEach(() => vi.restoreAllMocks());

describe('report view', () => {
  it('shows a table with totals and a CSV with neutralised formulas', () => {
    render(<ReportView result={result()} chart="table" title="By priority" />);
    const table = screen.getByRole('table', { name: 'By priority' });
    expect(within(table).getByRole('columnheader', { name: 'Estimate (h)' })).toBeInTheDocument();
    expect(within(table).getByRole('rowheader', { name: 'Total' }).closest('tr')).toHaveTextContent(
      'Total31.5 h',
    );
    const csv = resultToCsv(result({ rows: [{ keys: ['x'], labels: ['=SUM(A1)'], values: [1, 0] }] }));
    expect(csv.split('\n')[1]).toBe("'=SUM(A1),1,0");
  });

  it('shows a single number against its target in words, not colour alone', () => {
    const one = result({
      columns: [{ key: 'open', label: 'Open', kind: 'measure', unit: 'count' }],
      rows: [],
      totals: [7],
    });
    const { rerender } = render(
      <ReportView result={one} chart="kpi" title="Open work" target={{ value: 5, good: 'down' }} />,
    );
    expect(screen.getByLabelText('Open work: 7')).toBeInTheDocument();
    expect(screen.getByText(/Off target/)).toHaveTextContent('Off target (target at most 5)');
    rerender(<ReportView result={one} chart="kpi" title="Open work" target={{ value: 5, good: 'up' }} />);
    expect(screen.getByText(/On target/)).toBeInTheDocument();
  });

  it('says when rows were cut off', () => {
    render(<ReportView result={result({ truncated: true, total_groups: 80 })} chart="bar" title="t" />);
    expect(screen.getByText('Showing 2 of 80 groups; totals include all of them.')).toBeInTheDocument();
  });
});

describe('report builder', () => {
  it('previews as you change the definition and saves it', async () => {
    const created = { ...saved, id: 'r9', name: 'Overdue work by person' };
    const { calls } = mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/reports', body: [] },
      { method: 'POST', path: '/api/v1/reports/run', body: result() },
      { method: 'POST', path: '/api/v1/reports', status: 201, body: created },
      { method: 'GET', path: '/api/v1/reports/r9', body: created },
      { method: 'GET', path: '/api/v1/dashboards', body: [] },
    ]);
    renderAt('/reports');
    await userEvent.click(await screen.findByRole('link', { name: /Overdue work by person/ }));
    expect(await screen.findByRole('heading', { name: 'New report', level: 1 })).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveValue('Overdue work by person');
    await screen.findByRole('table', { name: 'Overdue work by person' });
    const runs = () => calls.filter((c) => c.method === 'POST' && c.url.endsWith('/reports/run'));
    expect(await runs()[0]!.clone().json()).toMatchObject({
      group_by: ['assignee'],
      measures: ['open', 'overdue'],
    });

    await userEvent.selectOptions(screen.getByLabelText('Group by'), 'Priority');
    await userEvent.click(screen.getByRole('checkbox', { name: 'Estimate (hours)' }));
    await waitFor(async () =>
      expect(await runs().at(-1)!.clone().json()).toMatchObject({
        group_by: ['priority'],
        measures: ['open', 'overdue', 'estimate_hours'],
      }),
    );

    await userEvent.click(screen.getByRole('button', { name: 'Save report' }));
    await waitFor(() => expect(window.location.pathname).toBe('/reports/r9'));
    const post = calls.find((c) => c.method === 'POST' && c.url.endsWith('/api/v1/reports'))!;
    expect(await post.json()).toMatchObject({
      name: 'Overdue work by person',
      shared: false,
      definition: { group_by: ['priority'] },
    });
  });

  it('switching to logged time starts from hours by project', async () => {
    const { calls } = mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'POST', path: '/api/v1/reports/run', body: result() },
    ]);
    renderAt('/reports/new');
    await userEvent.selectOptions(await screen.findByLabelText('Source'), 'Logged time');
    expect(screen.getByRole('checkbox', { name: 'Hours' })).toBeChecked();
    expect(screen.queryByRole('group', { name: /Priority/ })).toBeNull();
    await waitFor(async () =>
      expect(
        await calls
          .filter((c) => c.url.endsWith('/reports/run'))
          .at(-1)!
          .clone()
          .json(),
      ).toMatchObject({ source: 'time', group_by: ['project'], measures: ['hours'] }),
    );
  });
});

describe('dashboard report tiles', () => {
  it('runs report tiles with the dashboard filters', async () => {
    const dashboard = {
      id: 'd1',
      owner_id: 'u1',
      name: 'KPIs',
      shared: false,
      widgets: [
        {
          id: 'k',
          type: 'report',
          width: 1,
          title: '',
          config: { report_id: 'r1', target: 5, good: 'down' },
        },
      ],
      created_at: '',
      updated_at: '',
    };
    const { calls } = mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/dashboards/d1', body: dashboard },
      { method: 'GET', path: '/api/v1/reports', body: [saved] },
      {
        method: 'POST',
        path: '/api/v1/reports/r1/run',
        body: result({
          columns: [{ key: 'open', label: 'Open', kind: 'measure', unit: 'count' }],
          rows: [],
          totals: [3],
        }),
      },
    ]);
    renderAt('/dashboards/d1');
    const tile = await screen.findByRole('region', { name: 'Open work' });
    expect(await within(tile).findByText(/On target/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText('Date range (report tiles)'), 'Last 7 days');
    await waitFor(() => expect(calls.filter((c) => c.url.endsWith('/reports/r1/run'))).toHaveLength(2));
    const last = calls.filter((c) => c.url.endsWith('/reports/r1/run')).at(-1)!;
    expect(await last.json()).toEqual({ date: { preset: 'last_7_days' }, project_ids: [] });
    expect(new URLSearchParams(window.location.search).get('range')).toBe('last_7_days');
  });
});

describe('asking about reports', () => {
  const aiReports: Route = {
    ...aiOn,
    body: { ...(aiOn.body as object), features: ['search', 'reports'] },
  };
  const answer = (overrides: object = {}) => ({
    question: 'Which priority is most overdue?',
    answer: 'High has the most.\n\n![x](https://evil.example/?leak) [click](https://evil.example)',
    explanation: 'Tasks by priority',
    saved_report_id: null,
    saved_report_name: null,
    definition: { ...saved.definition, group_by: ['priority'], measures: ['count'], chart: 'table' },
    result: result(),
    usage: { input_tokens: 1, output_tokens: 1, provider: 'fake', model: 'fake' },
    ...overrides,
  });

  it('is hidden unless the feature is on', async () => {
    mockApi([...baseRoutes, signedIn, { method: 'GET', path: '/api/v1/reports', body: [] }]);
    renderAt('/reports');
    await screen.findByRole('heading', { name: 'Your reports' });
    expect(screen.queryByRole('heading', { name: 'Ask a question' })).toBeNull();
  });

  it('answers in plain text beside the report and opens it in the builder', async () => {
    const { calls } = mockApi([
      aiReports,
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/reports', body: [] },
      { method: 'POST', path: '/api/v1/ai/reports', body: answer() },
      { method: 'POST', path: '/api/v1/reports/run', body: result() },
    ]);
    renderAt('/reports?ask=Which%20priority%20is%20most%20overdue%3F');
    expect(await screen.findByText('High has the most.')).toBeInTheDocument();
    expect(screen.getByLabelText('Question')).toHaveValue('Which priority is most overdue?');
    const ask = calls.find((c) => c.url.endsWith('/ai/reports'))!;
    expect(await ask.json()).toEqual({ question: 'Which priority is most overdue?', report_id: null });
    // Untrusted text never becomes a link or an image.
    expect(document.querySelector('img')).toBeNull();
    expect(screen.queryByRole('link', { name: 'click' })).toBeNull();
    expect(screen.getByRole('table', { name: 'Answer' })).toBeInTheDocument();
    expect(screen.getByText(/Report used: Tasks by priority/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('link', { name: 'Open in the report builder' }));
    expect(await screen.findByRole('heading', { name: 'New report', level: 1 })).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveValue('Which priority is most overdue?');
    await waitFor(async () =>
      expect(
        await calls
          .filter((c) => c.url.endsWith('/reports/run'))
          .at(-1)!
          .clone()
          .json(),
      ).toMatchObject({ group_by: ['priority'], measures: ['count'] }),
    );
  });

  it('asks about a saved report as it is', async () => {
    const { calls } = mockApi([
      aiReports,
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/reports/r1', body: saved },
      { method: 'GET', path: '/api/v1/dashboards', body: [] },
      { method: 'POST', path: '/api/v1/reports/run', body: result() },
      {
        method: 'POST',
        path: '/api/v1/ai/reports',
        body: answer({ saved_report_id: 'r1', saved_report_name: 'Open work', answer: 'Seven open.' }),
      },
    ]);
    renderAt('/reports/r1');
    await userEvent.type(await screen.findByLabelText('Question'), 'How many?');
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }));
    expect(await screen.findByText('Seven open.')).toBeInTheDocument();
    expect(screen.getByText(/From your saved report “Open work”/)).toBeInTheDocument();
    const ask = calls.find((c) => c.url.endsWith('/ai/reports'))!;
    expect(await ask.json()).toEqual({ question: 'How many?', report_id: 'r1' });
    expect(screen.queryByRole('link', { name: /Open “Open work”/ })).toBeNull();
  });
});

describe('report emails', () => {
  const sub = {
    report_id: 'r1',
    report_name: 'Open work',
    schedule: { frequency: 'weekly', weekday: 0, day: null, hour: 8, minute: 0, timezone: 'UTC' },
    attach_csv: true,
    next_run_at: '2026-10-12T08:00:00Z',
    last_sent_at: null,
    last_error: 'email delivery failed: SMTPAuthenticationError',
  };
  const routes = (status: object): Route[] => [
    { method: 'GET', path: '/api/v1/reports/r1/email', body: status },
    ...baseRoutes,
    signedIn,
    { method: 'GET', path: '/api/v1/reports/r1', body: saved },
    { method: 'GET', path: '/api/v1/dashboards', body: [] },
    { method: 'POST', path: '/api/v1/reports/run', body: result() },
    { method: 'PUT', path: '/api/v1/reports/r1/email', body: sub },
    { method: 'DELETE', path: '/api/v1/reports/r1/email', status: 204 },
    { method: 'POST', path: '/api/v1/reports/r1/email/send', body: { sent_to: 'ada@example.com' } },
  ];

  it('says when the server has no email', async () => {
    mockApi(routes({ available: false, subscription: null }));
    renderAt('/reports/r1');
    expect(await screen.findByText(/Email isn’t set up on this server yet/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Start emails' })).toBeNull();
  });

  it('starts a schedule, sends now and shows the last error', async () => {
    const { calls } = mockApi(routes({ available: true, subscription: null }));
    renderAt('/reports/r1');
    const panel = (await screen.findByRole('heading', { name: 'Email me this report' })).closest('section')!;
    await userEvent.selectOptions(within(panel).getByLabelText('Repeat'), 'Monthly');
    await userEvent.clear(within(panel).getByLabelText('Day of month'));
    await userEvent.type(within(panel).getByLabelText('Day of month'), '15');
    await userEvent.click(within(panel).getByRole('checkbox', { name: 'Attach CSV' }));
    await userEvent.click(within(panel).getByRole('button', { name: 'Email me now' }));
    expect(await screen.findByText('Sent to ada@example.com')).toBeInTheDocument();
    const send = calls.find((c) => c.url.includes('/email/send'))!;
    expect(new URL(send.url).searchParams.get('attach_csv')).toBe('false');
    await userEvent.click(within(panel).getByRole('button', { name: 'Start emails' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true));
    const put = calls.find((c) => c.method === 'PUT')!;
    expect(await put.json()).toMatchObject({
      schedule: { frequency: 'monthly', day: 15, weekday: null, hour: 8 },
      attach_csv: false,
    });
  });

  it('shows an existing schedule and stops it', async () => {
    const { calls } = mockApi(routes({ available: true, subscription: sub }));
    renderAt('/reports/r1');
    expect(await screen.findByRole('alert')).toHaveTextContent('SMTPAuthenticationError');
    const panel = screen.getByRole('heading', { name: 'Email me this report' }).closest('section')!;
    expect(within(panel).getByLabelText('Repeat')).toHaveValue('weekly');
    await userEvent.click(within(panel).getByRole('button', { name: 'Stop emails' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true));
  });
});

describe('report alerts', () => {
  const alert = {
    report_id: 'r1',
    report_name: 'Open work',
    measure: 'open',
    measure_label: 'Open',
    direction: 'above',
    threshold: 5,
    schedule: { frequency: 'daily', weekday: null, day: null, hour: 8, minute: 0, timezone: 'UTC' },
    email: false,
    state: 'triggered',
    last_value: 7,
    last_checked_at: '2026-10-09T08:00:00Z',
    last_error: null,
    next_run_at: '2026-10-10T08:00:00Z',
  };
  const routes = (current: object | null): Route[] => [
    { method: 'GET', path: '/api/v1/reports/r1/alert', body: current },
    ...baseRoutes,
    signedIn,
    { method: 'GET', path: '/api/v1/reports/r1', body: saved },
    { method: 'GET', path: '/api/v1/dashboards', body: [] },
    { method: 'POST', path: '/api/v1/reports/run', body: result() },
    { method: 'PUT', path: '/api/v1/reports/r1/alert', body: alert },
    {
      method: 'POST',
      path: '/api/v1/reports/r1/alert/check',
      body: { ...alert, last_value: 4, state: 'ok' },
    },
    { method: 'DELETE', path: '/api/v1/reports/r1/alert', status: 204 },
  ];

  it('creates an alert on one of the report measures', async () => {
    const { calls } = mockApi(routes(null));
    renderAt('/reports/r1');
    const panel = (await screen.findByRole('heading', { name: 'Alert me' })).closest('section')!;
    expect(within(panel).getByRole('button', { name: 'Create alert' })).toBeDisabled();
    expect(within(panel).queryByRole('checkbox', { name: 'Also email me' })).toBeNull(); // no email here
    await userEvent.selectOptions(within(panel).getByLabelText('Goes'), 'below');
    await userEvent.type(within(panel).getByLabelText('Number'), '2.5');
    await userEvent.click(within(panel).getByRole('button', { name: 'Create alert' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true));
    expect(await calls.find((c) => c.method === 'PUT')!.json()).toMatchObject({
      measure: 'open',
      direction: 'below',
      threshold: 2.5,
      schedule: { frequency: 'daily', hour: 8 },
      email: false,
    });
  });

  it('shows a triggered alert, checks now and removes it', async () => {
    const { calls } = mockApi(routes(alert));
    renderAt('/reports/r1');
    const panel = (await screen.findByRole('heading', { name: 'Alert me' })).closest('section')!;
    expect(within(panel).getByText(/Open is above 5/)).toBeInTheDocument();
    expect(within(panel).getByLabelText('Number')).toHaveValue(5);
    await userEvent.click(within(panel).getByRole('button', { name: 'Check now' }));
    expect(await screen.findByText('Open is 4')).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole('button', { name: 'Remove alert' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true));
  });
});
