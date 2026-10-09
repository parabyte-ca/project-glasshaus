import type { ReportDefinition, ReportResult } from '../api/client';

export type Source = 'tasks' | 'time';
export type Measure = NonNullable<ReportDefinition['measures']>[number];
export type Chart = NonNullable<ReportDefinition['chart']>;
export type DatePreset = NonNullable<NonNullable<NonNullable<ReportDefinition['filters']>['date']>['preset']>;

export const DIMENSIONS: Record<Source, [string, string][]> = {
  tasks: [
    ['project', 'Project'],
    ['status', 'Status'],
    ['status_category', 'Status category'],
    ['priority', 'Priority'],
    ['assignee', 'Assignee'],
    ['reporter', 'Reporter'],
    ['tag', 'Tag'],
    ['due_week', 'Due (week)'],
    ['due_month', 'Due (month)'],
    ['created_week', 'Created (week)'],
    ['created_month', 'Created (month)'],
    ['completed_week', 'Completed (week)'],
    ['completed_month', 'Completed (month)'],
  ],
  time: [
    ['project', 'Project'],
    ['person', 'Person'],
    ['task', 'Task'],
    ['day', 'Day'],
    ['week', 'Week'],
    ['month', 'Month'],
    ['billable', 'Billable or not'],
  ],
};

export const MEASURES: Record<Source, [Measure, string][]> = {
  tasks: [
    ['count', 'Number of tasks'],
    ['open', 'Open'],
    ['done', 'Done'],
    ['overdue', 'Overdue'],
    ['estimate_hours', 'Estimate (hours)'],
    ['avg_age_days', 'Average age of open tasks (days)'],
    ['avg_cycle_days', 'Average time to complete (days)'],
    ['on_time_pct', 'Completed on time (%)'],
  ],
  time: [
    ['hours', 'Hours'],
    ['billable_hours', 'Billable hours'],
    ['entries', 'Time entries'],
    ['people', 'People'],
  ],
};

export const DATE_PRESETS: [DatePreset, string][] = [
  ['last_7_days', 'Last 7 days'],
  ['last_30_days', 'Last 30 days'],
  ['last_90_days', 'Last 90 days'],
  ['this_month', 'This month'],
  ['last_month', 'Last month'],
  ['this_quarter', 'This quarter'],
  ['this_year', 'This year'],
  ['next_30_days', 'Next 30 days'],
  ['custom', 'Custom dates…'],
];

export const CHARTS: [Chart, string][] = [
  ['table', 'Table'],
  ['bar', 'Bar chart'],
  ['line', 'Line chart'],
  ['kpi', 'Single number'],
];

export const STATUS_CATEGORIES: [string, string][] = [
  ['backlog', 'Backlog'],
  ['todo', 'To do'],
  ['in_progress', 'In progress'],
  ['done', 'Done'],
  ['cancelled', 'Cancelled'],
];

export const PRIORITY_OPTIONS: [string, string][] = [
  ['urgent', 'Urgent'],
  ['high', 'High'],
  ['medium', 'Medium'],
  ['low', 'Low'],
  ['none', 'None'],
];

export function defaultDefinition(source: Source = 'tasks'): ReportDefinition {
  return {
    source,
    group_by: [source === 'tasks' ? 'status_category' : 'project'],
    measures: [source === 'tasks' ? 'count' : 'hours'],
    filters: source === 'time' ? { date: { field: 'spent', preset: 'last_30_days' } } : {},
    chart: 'bar',
    sort: { by: 'label', descending: false },
    limit: 50,
  };
}

type Unit = ReportResult['columns'][number]['unit'];

/** A number as people read it: hours with "h", percentages with "%", days with "d". */
export function formatValue(value: number | null | undefined, unit: Unit): string {
  if (value === null || value === undefined) return '—';
  const n = Number.isInteger(value)
    ? value.toLocaleString()
    : value.toLocaleString(undefined, { maximumFractionDigits: 1 });
  if (unit === 'hours') return `${n} h`;
  if (unit === 'percent') return `${n}%`;
  if (unit === 'days') return `${n} d`;
  return n;
}

function cell(value: string): string {
  const safe = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  return /[",\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

/** The result as CSV (formulas neutralised), with a totals row. */
export function resultToCsv(result: ReportResult): string {
  const dims = result.columns.filter((c) => c.kind === 'dimension').length;
  const lines = [result.columns.map((c) => cell(c.label)).join(',')];
  for (const row of result.rows) {
    lines.push([...row.labels.map(cell), ...row.values.map((v) => (v === null ? '' : String(v)))].join(','));
  }
  if (dims > 0) {
    lines.push(
      ['Total', ...Array(dims - 1).fill(''), ...result.totals.map((v) => (v === null ? '' : String(v)))].join(
        ',',
      ),
    );
  }
  return `${lines.join('\n')}\n`;
}

export function downloadText(filename: string, text: string, type = 'text/csv;charset=utf-8') {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
