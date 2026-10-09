import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useId, useState, type ReactNode } from 'react';
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router';

import {
  api,
  fieldError,
  unwrap,
  type Dashboard,
  type ReportDefinition,
  type SavedReport,
  type Widget,
} from '../api/client';
import { useAuth } from '../auth/useAuth';
import { AskReports } from '../components/AskReports';
import { LoadError } from '../components/PageState';
import { ReportView } from '../components/ReportView';
import { Button, ErrorText, Field, GhostButton, Input, linkClass, Select } from '../components/ui';
import { useAiStatus } from '../lib/ai';
import { useConfirm } from '../lib/confirm';
import { usePageTitle } from '../lib/pageTitle';
import {
  CHARTS,
  DATE_PRESETS,
  defaultDefinition,
  DIMENSIONS,
  downloadText,
  MEASURES,
  PRIORITY_OPTIONS,
  resultToCsv,
  STATUS_CATEGORIES,
  type Chart,
  type DatePreset,
  type Measure,
  type Source,
} from '../lib/reportMeta';
import { toast } from '../lib/toast';

/** Ready-made starting points; each opens in the builder to adjust and save. */
const TEMPLATES: { id: string; name: string; description: string; definition: ReportDefinition }[] = [
  {
    id: 'overdue-by-assignee',
    name: 'Overdue work by person',
    description: 'Open and overdue tasks for each assignee.',
    definition: {
      source: 'tasks',
      group_by: ['assignee'],
      measures: ['open', 'overdue'],
      filters: {},
      chart: 'table',
      sort: { by: 'overdue', descending: true },
      limit: 50,
    },
  },
  {
    id: 'throughput',
    name: 'Tasks completed per week',
    description: 'Completed tasks per week over the last 90 days.',
    definition: {
      source: 'tasks',
      group_by: ['completed_week'],
      measures: ['done'],
      filters: { date: { field: 'completed', preset: 'last_90_days' } },
      chart: 'line',
      sort: { by: 'label', descending: false },
      limit: 50,
    },
  },
  {
    id: 'on-time-by-project',
    name: 'On-time delivery by project',
    description: 'Share of tasks completed by their due date, last 90 days.',
    definition: {
      source: 'tasks',
      group_by: ['project'],
      measures: ['done', 'on_time_pct', 'avg_cycle_days'],
      filters: { date: { field: 'completed', preset: 'last_90_days' } },
      chart: 'bar',
      sort: { by: 'on_time_pct', descending: false },
      limit: 50,
    },
  },
  {
    id: 'hours-by-project',
    name: 'Hours by project this month',
    description: 'Hours and billable hours logged this month.',
    definition: {
      source: 'time',
      group_by: ['project'],
      measures: ['hours', 'billable_hours'],
      filters: { date: { field: 'spent', preset: 'this_month' } },
      chart: 'bar',
      sort: { by: 'hours', descending: true },
      limit: 50,
    },
  },
];

function useDebounced<T>(value: T, ms: number): T {
  const [current, setCurrent] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setCurrent(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return current;
}

function ReportList() {
  usePageTitle('Reports');
  const { user } = useAuth();
  const [params] = useSearchParams();
  const canAsk = useAiStatus().data?.features.includes('reports') ?? false;
  const reports = useQuery({ queryKey: ['reports'], queryFn: () => unwrap(api.GET('/api/v1/reports')) });
  const mine = reports.data?.filter((r) => r.owner_id === user.id) ?? [];
  const shared = reports.data?.filter((r) => r.owner_id !== user.id) ?? [];
  const card = (r: SavedReport) => (
    <li key={r.id}>
      <Link
        to={`/reports/${r.id}`}
        className="block rounded-lg border border-slate-200 p-4 hover:border-sky-600 focus-visible:outline-2 focus-visible:outline-sky-600 dark:border-slate-800"
      >
        <span className="font-medium">{r.name}</span>
        {r.shared && <span className="ml-2 text-xs text-slate-600 dark:text-slate-400">(shared)</span>}
        <span className="block text-sm text-slate-600 dark:text-slate-400">
          {r.description || (r.definition.source === 'time' ? 'Time report' : 'Task report')}
        </span>
      </Link>
    </li>
  );
  return (
    <div className="flex max-w-5xl flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Reports</h1>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Build your own reports from tasks and logged time. Everyone sees only the projects they can
            access.
          </p>
        </div>
        <Link
          to="/reports/new"
          className="rounded-lg bg-sky-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600"
        >
          New report
        </Link>
      </div>
      <ErrorText error={reports.error} />
      {canAsk && <AskReports key={params.get('ask') ?? ''} initial={params.get('ask') ?? ''} />}
      <section aria-labelledby="mine-h" className="flex flex-col gap-2">
        <h2 id="mine-h" className="text-lg font-semibold">
          Your reports
        </h2>
        {reports.isPending ? (
          <p role="status">Loading…</p>
        ) : mine.length === 0 ? (
          <p className="text-sm text-slate-600 dark:text-slate-400">None yet. Start from a template below.</p>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">{mine.map(card)}</ul>
        )}
      </section>
      {shared.length > 0 && (
        <section aria-labelledby="shared-h" className="flex flex-col gap-2">
          <h2 id="shared-h" className="text-lg font-semibold">
            Shared with you
          </h2>
          <ul className="grid gap-3 sm:grid-cols-2">{shared.map(card)}</ul>
        </section>
      )}
      <section aria-labelledby="templates-h" className="flex flex-col gap-2">
        <h2 id="templates-h" className="text-lg font-semibold">
          Templates
        </h2>
        <ul className="grid gap-3 sm:grid-cols-2">
          {TEMPLATES.map((t) => (
            <li key={t.id}>
              <Link
                to={`/reports/new?template=${t.id}`}
                className="block rounded-lg border border-dashed border-slate-300 p-4 hover:border-sky-600 focus-visible:outline-2 focus-visible:outline-sky-600 dark:border-slate-700"
              >
                <span className="font-medium">{t.name}</span>
                <span className="block text-sm text-slate-600 dark:text-slate-400">{t.description}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function CheckList({
  legend,
  options,
  selected,
  onChange,
  scroll = true,
}: {
  legend: string;
  options: [string, string][];
  selected: string[];
  onChange: (next: string[]) => void;
  scroll?: boolean;
}) {
  return (
    <fieldset className="flex flex-col gap-1">
      <legend className="text-sm font-medium">
        {legend}
        {selected.length > 0 && (
          <span className="font-normal text-slate-600 dark:text-slate-400">
            {' '}
            ({selected.length} selected)
          </span>
        )}
      </legend>
      <div className={`flex flex-col gap-1 ${scroll ? 'max-h-40 overflow-y-auto pr-1' : ''}`}>
        {options.map(([value, label]) => (
          <label key={value} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={selected.includes(value)}
              onChange={(e) =>
                onChange(e.target.checked ? [...selected, value] : selected.filter((v) => v !== value))
              }
            />
            {label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="flex flex-col gap-3 rounded-lg border border-slate-200 p-3 dark:border-slate-800">
      <legend className="px-1 text-sm font-semibold">{title}</legend>
      {children}
    </fieldset>
  );
}

function AddToDashboard({ reportId }: { reportId: string }) {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [target, setTarget] = useState('');
  const dashboards = useQuery({
    queryKey: ['dashboards'],
    queryFn: () => unwrap(api.GET('/api/v1/dashboards')),
  });
  const editable = (dashboards.data ?? []).filter(
    (d) => d.owner_id === user.id || user.org_role === 'owner' || user.org_role === 'admin',
  );
  const add = useMutation({
    mutationFn: async (d: Dashboard) => {
      const tile: Widget = {
        id: Math.random().toString(36).slice(2, 10),
        type: 'report',
        width: 1,
        title: '',
        config: { report_id: reportId },
      };
      return unwrap(
        api.PATCH('/api/v1/dashboards/{dashboard_id}', {
          params: { path: { dashboard_id: d.id } },
          body: { widgets: [...(d.widgets as Widget[]), tile] },
        }),
      );
    },
    onSuccess: (d) => {
      void queryClient.invalidateQueries({ queryKey: ['dashboard', d.id] });
      toast(`Added to “${d.name}”`);
      setTarget('');
    },
  });
  if (editable.length === 0) return null;
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        const d = editable.find((x) => x.id === target);
        if (d) add.mutate(d);
      }}
    >
      <Field label="Add to dashboard" id="add-to-dashboard">
        <Select id="add-to-dashboard" required value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="">Choose…</option>
          {editable.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </Select>
      </Field>
      <GhostButton type="submit" disabled={add.isPending}>
        Add
      </GhostButton>
      <ErrorText error={add.error} />
    </form>
  );
}

function ReportBuilder({ report }: { report?: SavedReport }) {
  const { user } = useAuth();
  const confirm = useConfirm();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const template = TEMPLATES.find((t) => t.id === params.get('template'));
  // A definition handed over by "Open in the report builder" after an AI answer.
  const handed = useLocation().state as { definition?: ReportDefinition; name?: string } | null;
  const [definition, setDefinition] = useState<ReportDefinition>(
    () =>
      (report?.definition as ReportDefinition | undefined) ??
      template?.definition ??
      handed?.definition ??
      defaultDefinition(),
  );
  const [name, setName] = useState(report?.name ?? template?.name ?? handed?.name ?? '');
  const [description, setDescription] = useState(report?.description ?? template?.description ?? '');
  const [shared, setShared] = useState(report?.shared ?? false);
  usePageTitle(report ? report.name : 'New report');
  const ids = useId();

  const source = (definition.source ?? 'tasks') as Source;
  const filters = definition.filters ?? {};
  const groupBy = definition.group_by ?? [];
  const measures = (definition.measures ?? []) as Measure[];
  const set = (patch: Partial<ReportDefinition>) => setDefinition((d) => ({ ...d, ...patch }));
  const setFilters = (patch: Partial<NonNullable<ReportDefinition['filters']>>) =>
    setDefinition((d) => ({ ...d, filters: { ...(d.filters ?? {}), ...patch } }));

  const projects = useQuery({ queryKey: ['projects'], queryFn: () => unwrap(api.GET('/api/v1/projects')) });
  const users = useQuery({ queryKey: ['users'], queryFn: () => unwrap(api.GET('/api/v1/users')) });
  const onlyProject = filters.project_ids?.length === 1 ? filters.project_ids[0]! : null;
  const fields = useQuery({
    queryKey: ['fields', onlyProject],
    enabled: source === 'tasks' && !!onlyProject,
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/projects/{project_id}/fields', { params: { path: { project_id: onlyProject! } } }),
      ),
  });
  const dimensionOptions: [string, string][] = [
    ...DIMENSIONS[source],
    ...(source === 'tasks' && onlyProject
      ? (fields.data ?? [])
          .filter((f) => f.type === 'select')
          .map((f): [string, string] => [`cf:${f.id}`, f.name])
      : []),
  ];

  const debounced = useDebounced(definition, 300);
  const preview = useQuery({
    queryKey: ['report-preview', debounced],
    placeholderData: keepPreviousData,
    queryFn: () => unwrap(api.POST('/api/v1/reports/run', { body: debounced })),
  });

  const canEdit =
    !report || report.owner_id === user.id || user.org_role === 'owner' || user.org_role === 'admin';
  const save = useMutation({
    mutationFn: () => {
      const body = { name, description, shared, definition };
      return report && canEdit
        ? unwrap(
            api.PATCH('/api/v1/reports/{report_id}', { params: { path: { report_id: report.id } }, body }),
          )
        : unwrap(api.POST('/api/v1/reports', { body }));
    },
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: ['reports'] });
      queryClient.setQueryData(['report', saved.id], saved);
      toast(report && canEdit ? 'Report saved' : 'Report created');
      if (!report || !canEdit) void navigate(`/reports/${saved.id}`, { replace: !report });
    },
  });
  const remove = useMutation({
    mutationFn: () =>
      unwrap(api.DELETE('/api/v1/reports/{report_id}', { params: { path: { report_id: report!.id } } })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['reports'] });
      toast('Report deleted');
      void navigate('/reports');
    },
  });

  const date = filters.date ?? null;
  const dateFieldOptions: [string, string][] =
    source === 'tasks'
      ? [
          ['created', 'Created'],
          ['completed', 'Completed'],
          ['due', 'Due'],
        ]
      : [['spent', 'Day logged']];
  const sortValue = `${definition.sort?.by ?? 'label'}:${definition.sort?.descending ? 'desc' : 'asc'}`;
  const title = name || 'Untitled report';

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link to="/reports" className={`text-sm ${linkClass}`}>
          ← Reports
        </Link>
        <h1 className="text-2xl font-bold">{report ? report.name : 'New report'}</h1>
      </div>
      <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
        <form
          aria-label="Report definition"
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <Panel title="Data">
            <Field label="Source" id={`${ids}-source`}>
              <Select
                id={`${ids}-source`}
                value={source}
                onChange={(e) => setDefinition(defaultDefinition(e.target.value as Source))}
              >
                <option value="tasks">Tasks</option>
                <option value="time">Logged time</option>
              </Select>
            </Field>
            {[0, 1].map((i) => (
              <Field key={i} label={i === 0 ? 'Group by' : 'Then by'} id={`${ids}-group-${i}`}>
                <Select
                  id={`${ids}-group-${i}`}
                  value={groupBy[i] ?? ''}
                  disabled={i === 1 && !groupBy[0]}
                  onChange={(e) => {
                    const next = [...groupBy];
                    if (e.target.value) next[i] = e.target.value;
                    else next.splice(i);
                    set({ group_by: next.filter(Boolean) });
                  }}
                >
                  <option value="">{i === 0 ? 'No grouping (totals only)' : 'Nothing'}</option>
                  {dimensionOptions
                    .filter(([v]) => v === groupBy[i] || !groupBy.includes(v))
                    .map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                </Select>
              </Field>
            ))}
            {source === 'tasks' && !onlyProject && (
              <p className="text-xs text-slate-600 dark:text-slate-400">
                Filter to one project to group by its custom fields.
              </p>
            )}
            <CheckList
              legend="Measures"
              scroll={false}
              options={MEASURES[source]}
              selected={measures}
              onChange={(next) => {
                const kept = next.length ? (next as Measure[]) : measures;
                const sortBy = definition.sort?.by ?? 'label';
                set({
                  measures: kept.slice(0, 6),
                  sort:
                    sortBy === 'label' || kept.includes(sortBy as Measure)
                      ? definition.sort
                      : { by: 'label' },
                });
              }}
            />
          </Panel>

          <Panel title="Filters">
            <CheckList
              legend="Projects"
              options={(projects.data ?? []).map((p) => [p.id, `${p.key} ${p.name}`])}
              selected={filters.project_ids ?? []}
              onChange={(project_ids) => setFilters({ project_ids })}
            />
            <CheckList
              legend={source === 'tasks' ? 'Assignees' : 'People'}
              options={(users.data ?? []).map((u) => [u.id, u.name])}
              selected={filters.people ?? []}
              onChange={(people) => setFilters({ people })}
            />
            <Field label="Date range" id={`${ids}-preset`}>
              <Select
                id={`${ids}-preset`}
                value={date?.preset ?? ''}
                onChange={(e) =>
                  setFilters({
                    date: e.target.value
                      ? {
                          field: date?.field ?? (source === 'time' ? 'spent' : 'created'),
                          preset: e.target.value as DatePreset,
                          date_from: date?.date_from ?? null,
                          date_to: date?.date_to ?? null,
                        }
                      : null,
                  })
                }
              >
                <option value="">Any time</option>
                {DATE_PRESETS.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </Select>
            </Field>
            {date && source === 'tasks' && (
              <Field label="Date of" id={`${ids}-datefield`}>
                <Select
                  id={`${ids}-datefield`}
                  value={date.field ?? 'created'}
                  onChange={(e) => setFilters({ date: { ...date, field: e.target.value as 'created' } })}
                >
                  {dateFieldOptions.map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </Select>
              </Field>
            )}
            {date?.preset === 'custom' && (
              <div className="flex flex-wrap gap-2">
                <Field label="From" id={`${ids}-from`}>
                  <Input
                    id={`${ids}-from`}
                    type="date"
                    required
                    value={date.date_from ?? ''}
                    onChange={(e) => setFilters({ date: { ...date, date_from: e.target.value || null } })}
                  />
                </Field>
                <Field label="To" id={`${ids}-to`}>
                  <Input
                    id={`${ids}-to`}
                    type="date"
                    required
                    value={date.date_to ?? ''}
                    onChange={(e) => setFilters({ date: { ...date, date_to: e.target.value || null } })}
                  />
                </Field>
              </div>
            )}
            {source === 'tasks' ? (
              <>
                <CheckList
                  legend="Status"
                  options={STATUS_CATEGORIES}
                  selected={(filters.status_categories as string[] | undefined) ?? []}
                  onChange={(v) => setFilters({ status_categories: v as never })}
                />
                <CheckList
                  legend="Priority"
                  options={PRIORITY_OPTIONS}
                  selected={(filters.priorities as string[] | undefined) ?? []}
                  onChange={(v) => setFilters({ priorities: v as never })}
                />
                <Field label="Tags (any of, comma separated)" id={`${ids}-tags`}>
                  <Input
                    id={`${ids}-tags`}
                    value={(filters.tags ?? []).join(', ')}
                    onChange={(e) =>
                      setFilters({
                        tags: e.target.value
                          .split(',')
                          .map((t) => t.trim())
                          .filter(Boolean),
                      })
                    }
                  />
                </Field>
              </>
            ) : (
              <Field label="Billable" id={`${ids}-billable`}>
                <Select
                  id={`${ids}-billable`}
                  value={filters.billable === true ? 'yes' : filters.billable === false ? 'no' : ''}
                  onChange={(e) =>
                    setFilters({ billable: e.target.value === '' ? null : e.target.value === 'yes' })
                  }
                >
                  <option value="">Billable and not</option>
                  <option value="yes">Billable only</option>
                  <option value="no">Not billable only</option>
                </Select>
              </Field>
            )}
          </Panel>

          <Panel title="Display">
            <Field label="Show as" id={`${ids}-chart`}>
              <Select
                id={`${ids}-chart`}
                value={definition.chart ?? 'table'}
                onChange={(e) => set({ chart: e.target.value as Chart })}
              >
                {CHARTS.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Sort" id={`${ids}-sort`}>
              <Select
                id={`${ids}-sort`}
                value={sortValue}
                onChange={(e) => {
                  const [by, dir] = e.target.value.split(':') as [string, string];
                  set({ sort: { by, descending: dir === 'desc' } });
                }}
              >
                <option value="label:asc">By name or date (A–Z, oldest first)</option>
                <option value="label:desc">By name or date (Z–A, newest first)</option>
                {measures.map((m) => {
                  const label = MEASURES[source].find(([v]) => v === m)?.[1] ?? m;
                  return [
                    <option key={`${m}:desc`} value={`${m}:desc`}>
                      {label}: highest first
                    </option>,
                    <option key={`${m}:asc`} value={`${m}:asc`}>
                      {label}: lowest first
                    </option>,
                  ];
                })}
              </Select>
            </Field>
            <Field label="Rows" id={`${ids}-limit`}>
              <Select
                id={`${ids}-limit`}
                value={definition.limit ?? 50}
                onChange={(e) => set({ limit: Number(e.target.value) })}
              >
                {[10, 25, 50, 100, 500].map((n) => (
                  <option key={n} value={n}>
                    Up to {n}
                  </option>
                ))}
              </Select>
            </Field>
          </Panel>

          <Panel title="Save">
            <Field label="Name" id={`${ids}-name`} error={fieldError(save.error, 'name')}>
              <Input
                id={`${ids}-name`}
                required
                maxLength={100}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <Field
              label="Description (optional)"
              id={`${ids}-desc`}
              error={fieldError(save.error, 'description')}
            >
              <Input
                id={`${ids}-desc`}
                maxLength={500}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </Field>
            {user.org_role !== 'guest' && canEdit && (
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} />
                Share with everyone (each person sees only data they can access)
              </label>
            )}
            <div className="flex flex-wrap gap-2">
              <Button type="submit" disabled={save.isPending}>
                {report && !canEdit ? 'Save a copy' : 'Save report'}
              </Button>
              {report && canEdit && (
                <GhostButton
                  onClick={async () =>
                    (await confirm({
                      title: `Delete the report “${report.name}”?`,
                      body: 'Dashboard tiles that show it will say it is missing.',
                      confirmLabel: 'Delete',
                      danger: true,
                    })) && remove.mutate()
                  }
                >
                  Delete
                </GhostButton>
              )}
            </div>
            <ErrorText error={save.error ?? remove.error} />
          </Panel>
        </form>

        <section aria-labelledby={`${ids}-preview`} className="flex min-w-0 flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id={`${ids}-preview`} className="text-lg font-semibold">
              {title}
            </h2>
            <div className="flex flex-wrap items-end gap-2">
              <GhostButton
                disabled={!preview.data}
                onClick={() =>
                  preview.data &&
                  downloadText(`${title.replace(/[^\w.-]+/g, '-')}.csv`, resultToCsv(preview.data))
                }
              >
                Download CSV
              </GhostButton>
              {report && <AddToDashboard reportId={report.id} />}
            </div>
          </div>
          {preview.data?.date_from && (
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {preview.data.date_from} to {preview.data.date_to}
            </p>
          )}
          <div aria-busy={preview.isFetching} className={preview.isFetching ? 'opacity-70' : ''}>
            {preview.isPending ? (
              <p role="status">Running the report…</p>
            ) : preview.error ? (
              <ErrorText error={preview.error} />
            ) : preview.data ? (
              <ReportView
                result={preview.data}
                chart={(definition.chart ?? 'table') as Chart}
                title={title}
              />
            ) : null}
          </div>
        </section>
      </div>
    </div>
  );
}

function SavedReportBuilder({ id }: { id: string }) {
  const canAsk = useAiStatus().data?.features.includes('reports') ?? false;
  const report = useQuery({
    queryKey: ['report', id],
    queryFn: () => unwrap(api.GET('/api/v1/reports/{report_id}', { params: { path: { report_id: id } } })),
  });
  if (report.error)
    return <LoadError error={report.error} what="report" onRetry={() => void report.refetch()} />;
  if (!report.data) return <p role="status">Loading…</p>;
  return (
    <div className="flex flex-col gap-8">
      <ReportBuilder key={report.data.id} report={report.data} />
      {canAsk && (
        <div className="max-w-5xl">
          <AskReports key={report.data.id} reportId={report.data.id} />
        </div>
      )}
    </div>
  );
}

export function ReportsPage() {
  const { reportId } = useParams();
  const [params] = useSearchParams();
  if (!reportId) return <ReportList />;
  if (reportId === 'new') return <ReportBuilder key={params.get('template') ?? 'new'} />;
  return <SavedReportBuilder id={reportId} />;
}
