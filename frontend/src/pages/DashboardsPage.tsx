import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type DragEvent, type FormEvent, type ReactNode } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router';

import {
  api,
  unwrap,
  type Dashboard,
  type ReportOverrides,
  type SavedReport,
  type Widget,
} from '../api/client';
import { useAuth } from '../auth/useAuth';
import { HealthBadge, ProgressBar } from '../components/charts';
import { Burnup, ProjectHealthCard, StatusMix, Throughput } from '../components/ReportWidgets';
import { useReport } from '../lib/reports';
import { Button, ErrorText, Field, GhostButton, Input, linkClass, Select } from '../components/ui';
import { addDays, todayIso } from '../lib/dates';
import { formatMinutes, hours, mondayOf } from '../lib/format';
import { usePageTitle } from '../lib/pageTitle';
import { LoadError } from '../components/PageState';
import { ReportTile } from '../components/ReportTile';
import { DATE_PRESETS, type DatePreset } from '../lib/reportMeta';
import { useConfirm } from '../lib/confirm';

type WidgetType = Widget['type'];

const TYPES: {
  value: WidgetType;
  label: string;
  needs?: 'project' | 'portfolio' | 'objective' | 'report';
}[] = [
  { value: 'report', label: 'Saved report or number', needs: 'report' },
  { value: 'my_tasks', label: 'My open tasks' },
  { value: 'my_time', label: 'My time this week' },
  { value: 'time_by_project', label: 'Team time by project (30 days)' },
  { value: 'workload', label: 'Workload this week' },
  { value: 'project_status', label: 'Project status', needs: 'project' },
  { value: 'burnup', label: 'Burn-up', needs: 'project' },
  { value: 'throughput', label: 'Throughput', needs: 'project' },
  { value: 'portfolio', label: 'Portfolio health', needs: 'portfolio' },
  { value: 'objective', label: 'Objective progress', needs: 'objective' },
];

function str(config: Widget['config'], key: string): string {
  const v = config?.[key];
  return typeof v === 'string' ? v : '';
}

function MyTasks() {
  const { user } = useAuth();
  const tasks = useQuery({
    queryKey: ['tasks', 'mine', user.id],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/tasks', {
          params: {
            query: {
              assignee_ids: [user.id],
              status_categories: ['backlog', 'todo', 'in_progress'],
              sort: 'due_date',
              limit: 10,
            },
          },
        }),
      ),
  });
  if (tasks.data?.items.length === 0)
    return <p className="text-sm text-slate-600 dark:text-slate-400">Nothing assigned.</p>;
  return (
    <ul className="flex flex-col gap-1 text-sm">
      {tasks.data?.items.map((t) => (
        <li key={t.id} className="flex justify-between gap-2">
          <Link to={`/projects/${t.key.split('-')[0]}?task=${t.key}`} className="truncate hover:underline">
            <span className="mr-2 font-mono text-xs">{t.key}</span>
            {t.title}
          </Link>
          {t.due_date && (
            <span className="shrink-0 text-xs text-slate-600 dark:text-slate-400">{t.due_date}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

function MyTime() {
  const week = mondayOf(todayIso());
  const sheet = useQuery({
    queryKey: ['timesheet', 'me', week],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/timesheets', { params: { query: { date_from: week, date_to: addDays(week, 6) } } }),
      ),
  });
  const s = sheet.data;
  if (!s) return null;
  return (
    <div>
      <p className="text-2xl font-semibold">{formatMinutes(s.total)}</p>
      <ul className="mt-1 text-xs text-slate-600 dark:text-slate-400">
        {s.rows.slice(0, 5).map((r) => (
          <li key={r.task_id}>
            {r.task_key} · {formatMinutes(r.total)}
          </li>
        ))}
      </ul>
    </div>
  );
}

function TimeByProject() {
  const report = useQuery({
    queryKey: ['time-report', 'dashboard'],
    queryFn: () => unwrap(api.GET('/api/v1/reports/time')),
  });
  const totals = new Map<string, { key: string; minutes: number }>();
  for (const r of report.data?.rows ?? []) {
    const t = totals.get(r.project_id) ?? { key: r.project_key, minutes: 0 };
    t.minutes += r.minutes;
    totals.set(r.project_id, t);
  }
  const rows = [...totals.values()].sort((a, b) => b.minutes - a.minutes);
  const max = Math.max(1, ...rows.map((r) => r.minutes));
  if (!rows.length) return <p className="text-sm text-slate-600 dark:text-slate-400">No time logged.</p>;
  return (
    <table className="w-full text-sm">
      <tbody>
        {rows.map((r) => (
          <tr key={r.key}>
            <th scope="row" className="w-16 py-0.5 text-left font-mono text-xs font-normal">
              {r.key}
            </th>
            <td>
              <div
                className="h-2 rounded-r"
                style={{ width: `${(r.minutes / max) * 100}%`, backgroundColor: 'var(--series-1)' }}
              />
            </td>
            <td className="w-14 text-right tabular-nums">{hours(r.minutes)}h</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function WorkloadSummary() {
  const week = mondayOf(todayIso());
  const data = useQuery({
    queryKey: ['workload', 'dashboard', week],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/workload', { params: { query: { date_from: week, date_to: addDays(week, 6) } } }),
      ),
  });
  return (
    <ul className="flex flex-col gap-1 text-sm">
      {data.data?.users.map((u) => (
        <li key={u.user_id}>
          <div className="flex justify-between text-xs">
            <span>{u.name}</span>
            <span className="tabular-nums">
              {hours(u.planned_total)} / {hours(u.capacity_total)}h
            </span>
          </div>
          <ProgressBar
            value={u.capacity_total ? u.planned_total / u.capacity_total : 0}
            label={`${u.name} booked`}
          />
        </li>
      ))}
    </ul>
  );
}

function ReportWidget({
  projectId,
  kind,
}: {
  projectId: string;
  kind: 'project_status' | 'burnup' | 'throughput';
}) {
  const report = useReport(projectId);
  if (report.error) return <ErrorText error={report.error} />;
  if (!report.data) return <p role="status">Loading…</p>;
  if (kind === 'burnup') return <Burnup report={report.data} />;
  if (kind === 'throughput') return <Throughput report={report.data} />;
  return (
    <div className="flex flex-col gap-3">
      <ProjectHealthCard projectId={projectId} />
      <StatusMix report={report.data} />
    </div>
  );
}

function PortfolioWidget({ id }: { id: string }) {
  const p = useQuery({
    queryKey: ['portfolio', id],
    queryFn: () =>
      unwrap(api.GET('/api/v1/portfolios/{portfolio_id}', { params: { path: { portfolio_id: id } } })),
  });
  if (p.error) return <ErrorText error={p.error} />;
  return (
    <ul className="flex flex-col gap-2 text-sm">
      {p.data?.projects.map((h) => (
        <li key={h.project_id} className="flex flex-col gap-0.5">
          <div className="flex justify-between">
            <span className="font-mono text-xs">{h.key}</span>
            <HealthBadge health={h.health} />
          </div>
          <ProgressBar value={h.progress} label={`${h.key} progress`} />
        </li>
      ))}
    </ul>
  );
}

function ObjectiveWidget({ id }: { id: string }) {
  const o = useQuery({
    queryKey: ['objectives', 'one', id],
    queryFn: () =>
      unwrap(api.GET('/api/v1/objectives/{objective_id}', { params: { path: { objective_id: id } } })),
  });
  if (o.error) return <ErrorText error={o.error} />;
  if (!o.data) return null;
  return (
    <div className="flex flex-col gap-2 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">{o.data.title}</span>
        <HealthBadge health={o.data.confidence} />
      </div>
      {o.data.progress !== null && <ProgressBar value={o.data.progress} label="Objective progress" />}
      <ul className="text-xs text-slate-600 dark:text-slate-400">
        {o.data.key_results.map((kr) => (
          <li key={kr.id}>
            {kr.title}: {kr.progress !== null ? `${Math.round(kr.progress * 100)}%` : 'hidden'}
          </li>
        ))}
      </ul>
    </div>
  );
}

function WidgetBody({
  widget,
  reports,
  overrides,
}: {
  widget: Widget;
  reports: Map<string, SavedReport>;
  overrides: ReportOverrides | null;
}) {
  const config = widget.config ?? {};
  switch (widget.type) {
    case 'report':
      return (
        <ReportTile report={reports.get(str(config, 'report_id'))} config={config} overrides={overrides} />
      );
    case 'my_tasks':
      return <MyTasks />;
    case 'my_time':
      return <MyTime />;
    case 'time_by_project':
      return <TimeByProject />;
    case 'workload':
      return <WorkloadSummary />;
    case 'project_status':
    case 'burnup':
    case 'throughput':
      return <ReportWidget projectId={str(config, 'project_id')} kind={widget.type} />;
    case 'portfolio':
      return <PortfolioWidget id={str(config, 'portfolio_id')} />;
    case 'objective':
      return <ObjectiveWidget id={str(config, 'objective_id')} />;
  }
}

const SPAN = { 1: 'md:col-span-1', 2: 'md:col-span-2', 3: 'md:col-span-3' } as const;

function WidgetFrame({
  widget,
  children,
  controls,
  title: fallback,
  drag,
}: {
  widget: Widget;
  children: ReactNode;
  controls?: ReactNode;
  title?: string;
  drag?: {
    onDragStart: (e: DragEvent) => void;
    onDragEnter: () => void;
    onDrop: (e: DragEvent) => void;
    over: boolean;
  };
}) {
  const title = widget.title || fallback || TYPES.find((t) => t.value === widget.type)?.label;
  return (
    <section
      aria-label={title}
      draggable={!!drag}
      onDragStart={drag?.onDragStart}
      onDragOver={drag ? (e) => e.preventDefault() : undefined}
      onDragEnter={drag?.onDragEnter}
      onDrop={drag?.onDrop}
      className={`rounded-lg border p-4 ${drag ? 'cursor-move' : ''} ${drag?.over ? 'border-sky-600' : 'border-slate-200 dark:border-slate-800'} ${SPAN[(widget.width ?? 1) as 1 | 2 | 3]}`}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{title}</h2>
        {controls}
      </div>
      {children}
    </section>
  );
}

function AddWidget({ onAdd }: { onAdd: (w: Widget) => void }) {
  const [type, setType] = useState<WidgetType>('my_tasks');
  const [target, setTarget] = useState('');
  const [width, setWidth] = useState(1);
  const needs = TYPES.find((t) => t.value === type)?.needs;
  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => unwrap(api.GET('/api/v1/projects')),
    enabled: needs === 'project',
  });
  const portfolios = useQuery({
    queryKey: ['portfolios'],
    queryFn: () => unwrap(api.GET('/api/v1/portfolios')),
    enabled: needs === 'portfolio',
  });
  const objectives = useQuery({
    queryKey: ['objectives', ''],
    queryFn: () => unwrap(api.GET('/api/v1/objectives')),
    enabled: needs === 'objective',
  });
  const reports = useQuery({
    queryKey: ['reports'],
    queryFn: () => unwrap(api.GET('/api/v1/reports')),
    enabled: needs === 'report',
  });
  const [goal, setGoal] = useState('');
  const [good, setGood] = useState<'up' | 'down'>('up');
  const chosenReport = needs === 'report' ? reports.data?.find((r) => r.id === target) : undefined;
  const isNumber =
    chosenReport?.definition.chart === 'kpi' || chosenReport?.definition.group_by?.length === 0;
  const options =
    needs === 'project'
      ? projects.data?.map((p) => [p.id, `${p.key} — ${p.name}`] as const)
      : needs === 'portfolio'
        ? portfolios.data?.map((p) => [p.id, p.name] as const)
        : needs === 'report'
          ? reports.data?.map((r) => [r.id, r.name] as const)
          : objectives.data?.map((o) => [o.id, `${o.period}: ${o.title}`] as const);
  return (
    <form
      aria-label="Add widget"
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        onAdd({
          id: Math.random().toString(36).slice(2, 10),
          type,
          width,
          title: '',
          config: needs
            ? {
                [`${needs}_id`]: target,
                ...(isNumber && goal !== '' ? { target: Number(goal), good } : {}),
              }
            : {},
        });
        setTarget('');
        setGoal('');
      }}
    >
      <Field label="Widget" id="w-type">
        <Select
          id="w-type"
          value={type}
          onChange={(e) => {
            setType(e.target.value as WidgetType);
            setTarget('');
          }}
        >
          {TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </Select>
      </Field>
      {needs === 'report' && reports.data?.length === 0 && (
        <p className="text-sm text-slate-600 dark:text-slate-400">
          No saved reports yet.{' '}
          <Link to="/reports/new" className={linkClass}>
            Build one
          </Link>
          .
        </p>
      )}
      {needs && (
        <Field label={needs[0]!.toUpperCase() + needs.slice(1)} id="w-target">
          <Select id="w-target" required value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">Choose…</option>
            {options?.map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
      )}
      {isNumber && (
        <>
          <Field label="Target (optional)" id="w-goal">
            <Input
              id="w-goal"
              type="number"
              step="any"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
            />
          </Field>
          <Field label="Good when" id="w-good">
            <Select id="w-good" value={good} onChange={(e) => setGood(e.target.value as 'up' | 'down')}>
              <option value="up">At or above target</option>
              <option value="down">At or below target</option>
            </Select>
          </Field>
        </>
      )}
      <Field label="Width" id="w-width">
        <Select id="w-width" value={width} onChange={(e) => setWidth(Number(e.target.value))}>
          <option value={1}>Narrow</option>
          <option value={2}>Wide</option>
          <option value={3}>Full</option>
        </Select>
      </Field>
      <GhostButton type="submit">Add widget</GhostButton>
    </form>
  );
}

function DashboardView({ id }: { id: string }) {
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { user } = useAuth();
  const dashboard = useQuery({
    queryKey: ['dashboard', id],
    queryFn: () =>
      unwrap(api.GET('/api/v1/dashboards/{dashboard_id}', { params: { path: { dashboard_id: id } } })),
  });
  const [editing, setEditing] = useState(false);
  const [dragFrom, setDragFrom] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState<number | null>(null);
  const [params, setParams] = useSearchParams();
  const hasReports =
    (dashboard.data?.widgets as Widget[] | undefined)?.some((w) => w.type === 'report') ?? false;
  const reportList = useQuery({
    queryKey: ['reports'],
    queryFn: () => unwrap(api.GET('/api/v1/reports')),
    enabled: hasReports,
  });
  const projectList = useQuery({
    queryKey: ['projects'],
    queryFn: () => unwrap(api.GET('/api/v1/projects')),
    enabled: hasReports,
  });
  const reports = new Map((reportList.data ?? []).map((r) => [r.id, r]));
  // Dashboard-wide filters for report tiles, kept in the address so a filtered view can be shared.
  const range = (params.get('range') ?? '') as DatePreset | '';
  const projectFilter = params.get('project') ?? '';
  const overrides: ReportOverrides | null =
    range || projectFilter
      ? {
          ...(range ? { date: { preset: range } } : {}),
          project_ids: projectFilter ? [projectFilter] : [],
        }
      : null;
  const setFilter = (key: string, value: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set(key, value);
        else next.delete(key);
        return next;
      },
      { replace: true },
    );
  const save = useMutation({
    mutationFn: (patch: { widgets?: Widget[]; shared?: boolean }) =>
      unwrap(
        api.PATCH('/api/v1/dashboards/{dashboard_id}', {
          params: { path: { dashboard_id: id } },
          body: patch,
        }),
      ),
    onSuccess: (d: Dashboard) => {
      queryClient.setQueryData(['dashboard', id], d);
      void queryClient.invalidateQueries({ queryKey: ['dashboards'] });
    },
  });
  const remove = useMutation({
    mutationFn: () =>
      unwrap(api.DELETE('/api/v1/dashboards/{dashboard_id}', { params: { path: { dashboard_id: id } } })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['dashboards'] });
      void navigate('/dashboards');
    },
  });
  usePageTitle(dashboard.data?.name ?? 'Dashboard');
  if (dashboard.error) {
    return <LoadError error={dashboard.error} what="dashboard" onRetry={() => void dashboard.refetch()} />;
  }
  if (!dashboard.data) return <p role="status">Loading…</p>;
  const d = dashboard.data;
  const widgets = d.widgets as Widget[];
  const canEdit = d.owner_id === user.id || user.org_role === 'owner' || user.org_role === 'admin';
  const moveTo = (from: number, to: number) => {
    if (from === to) return;
    const next = [...widgets];
    const [w] = next.splice(from, 1);
    next.splice(to, 0, w!);
    save.mutate({ widgets: next });
  };
  const move = (i: number, by: number) => moveTo(i, i + by);
  const change = (id: string, patch: Partial<Widget>) =>
    save.mutate({ widgets: widgets.map((w) => (w.id === id ? { ...w, ...patch } : w)) });
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link to="/dashboards" className={`text-sm ${linkClass}`}>
            ← Dashboards
          </Link>
          <h1 className="text-2xl font-bold">{d.name}</h1>
        </div>
        {canEdit && (
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={d.shared}
                onChange={(e) => save.mutate({ shared: e.target.checked })}
              />
              Shared with everyone
            </label>
            <GhostButton aria-pressed={editing} onClick={() => setEditing(!editing)}>
              {editing ? 'Done' : 'Edit'}
            </GhostButton>
            <GhostButton
              onClick={async () =>
                (await confirm({
                  title: `Delete the dashboard "${d.name}"?`,
                  confirmLabel: 'Delete',
                  danger: true,
                })) && remove.mutate()
              }
            >
              Delete
            </GhostButton>
          </div>
        )}
      </div>
      {editing && <AddWidget onAdd={(w) => save.mutate({ widgets: [...widgets, w] })} />}
      {editing && widgets.length > 1 && (
        <p className="text-xs text-slate-600 dark:text-slate-400">
          Drag tiles to reorder them, or use the arrow buttons.
        </p>
      )}
      {hasReports && (
        <div className="flex flex-wrap items-end gap-3" role="group" aria-label="Filters for report tiles">
          <Field label="Date range (report tiles)" id="dash-range">
            <Select id="dash-range" value={range} onChange={(e) => setFilter('range', e.target.value)}>
              <option value="">Each report's own</option>
              {DATE_PRESETS.filter(([v]) => v !== 'custom').map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Project (report tiles)" id="dash-project">
            <Select
              id="dash-project"
              value={projectFilter}
              onChange={(e) => setFilter('project', e.target.value)}
            >
              <option value="">Each report's own</option>
              {projectList.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.key} {p.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      )}
      <ErrorText error={save.error ?? remove.error} />
      {widgets.length === 0 && (
        <p className="text-sm text-slate-600 dark:text-slate-400">
          No widgets yet{canEdit ? ' — choose Edit to add some.' : '.'}
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-3">
        {widgets.map((w, i) => (
          <WidgetFrame
            key={w.id}
            widget={w}
            title={w.type === 'report' ? reports.get(str(w.config, 'report_id'))?.name : undefined}
            drag={
              editing
                ? {
                    over: dragOver === i && dragFrom !== i,
                    onDragStart: (e) => {
                      e.dataTransfer.effectAllowed = 'move';
                      e.dataTransfer.setData('text/plain', w.id);
                      setDragFrom(i);
                    },
                    onDragEnter: () => setDragOver(i),
                    onDrop: (e) => {
                      e.preventDefault();
                      if (dragFrom !== null) moveTo(dragFrom, i);
                      setDragFrom(null);
                      setDragOver(null);
                    },
                  }
                : undefined
            }
            controls={
              editing && (
                <span className="flex flex-wrap items-center gap-1">
                  <Select
                    aria-label={`Width of ${w.title || w.type}`}
                    className="px-1 py-0.5 text-xs"
                    value={w.width ?? 1}
                    onChange={(e) => change(w.id, { width: Number(e.target.value) })}
                  >
                    <option value={1}>Narrow</option>
                    <option value={2}>Wide</option>
                    <option value={3}>Full</option>
                  </Select>
                  <Input
                    aria-label={`Title of ${w.title || w.type} tile`}
                    className="w-32 px-2 py-0.5 text-xs"
                    placeholder="Default title"
                    maxLength={100}
                    defaultValue={w.title ?? ''}
                    onBlur={(e) =>
                      e.target.value !== (w.title ?? '') && change(w.id, { title: e.target.value })
                    }
                    onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
                  />
                  <GhostButton
                    className="px-2 py-0.5"
                    aria-label="Move earlier"
                    disabled={i === 0}
                    onClick={() => move(i, -1)}
                  >
                    ↑
                  </GhostButton>
                  <GhostButton
                    className="px-2 py-0.5"
                    aria-label="Move later"
                    disabled={i === widgets.length - 1}
                    onClick={() => move(i, 1)}
                  >
                    ↓
                  </GhostButton>
                  <GhostButton
                    className="px-2 py-0.5"
                    aria-label={`Remove ${w.type}`}
                    onClick={() => save.mutate({ widgets: widgets.filter((x) => x.id !== w.id) })}
                  >
                    ✕
                  </GhostButton>
                </span>
              )
            }
          >
            <WidgetBody widget={w} reports={reports} overrides={overrides} />
          </WidgetFrame>
        ))}
      </div>
    </div>
  );
}

const STARTER: Widget[] = [
  { id: 'tasks', type: 'my_tasks', width: 2, title: '', config: {} },
  { id: 'time', type: 'my_time', width: 1, title: '', config: {} },
  { id: 'workload', type: 'workload', width: 1, title: '', config: {} },
  { id: 'byproject', type: 'time_by_project', width: 2, title: '', config: {} },
];

function DashboardList() {
  usePageTitle('Dashboards');
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const dashboards = useQuery({
    queryKey: ['dashboards'],
    queryFn: () => unwrap(api.GET('/api/v1/dashboards')),
  });
  const [name, setName] = useState('');
  const create = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/dashboards', { body: { name, widgets: STARTER } })),
    onSuccess: (d) => {
      void queryClient.invalidateQueries({ queryKey: ['dashboards'] });
      void navigate(`/dashboards/${d.id}`);
    },
  });
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <h1 className="text-2xl font-bold">Dashboards</h1>
      <ul className="grid gap-3 sm:grid-cols-2">
        {dashboards.data?.length === 0 && (
          <li className="text-sm text-slate-600 dark:text-slate-400">No dashboards yet.</li>
        )}
        {dashboards.data?.map((d) => (
          <li key={d.id} className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
            <Link to={`/dashboards/${d.id}`} className="font-medium hover:underline">
              {d.name}
            </Link>
            <p className="text-xs text-slate-600 dark:text-slate-400">
              {d.widgets.length} widgets{d.shared ? ' · shared' : ''}
            </p>
          </li>
        ))}
      </ul>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <Field label="New dashboard" id="db-name">
          <Input
            id="db-name"
            required
            maxLength={100}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <Button type="submit" disabled={create.isPending}>
          Create
        </Button>
        <ErrorText error={create.error} />
      </form>
    </div>
  );
}

export function DashboardsPage() {
  const { dashboardId } = useParams();
  return dashboardId ? <DashboardView id={dashboardId} /> : <DashboardList />;
}
