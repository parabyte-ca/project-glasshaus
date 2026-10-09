import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ReportResult, SavedReport } from './api/client';
import App from './App';
import { ReportView } from './components/ReportView';
import { resultToCsv } from './lib/reportMeta';
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
