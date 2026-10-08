import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api, unwrap, type Workload } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { ErrorText, Field, GhostButton, Input, Select } from '../components/ui';
import { addDays, todayIso } from '../lib/dates';
import { formatMinutes, hours, mondayOf, shortDate } from '../lib/format';

type Person = Workload['users'][number];
type Cell = Person['buckets'][number];

function LoadCell({ cell }: { cell: Cell }) {
  const over = cell.planned > cell.capacity;
  const ratio = cell.capacity ? Math.min(cell.planned / cell.capacity, 1) : cell.planned ? 1 : 0;
  return (
    <td className="px-1 py-1.5 align-top">
      <div className="text-xs tabular-nums">
        {hours(cell.planned)} / {hours(cell.capacity)}h
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800" aria-hidden>
        <div
          className="h-full rounded-full"
          style={{
            width: `${Math.round(ratio * 100)}%`,
            backgroundColor: over ? 'var(--status-critical)' : 'var(--series-1)',
          }}
        />
      </div>
      {over && (
        <div className="mt-0.5 flex items-center gap-1 text-[11px] font-medium">
          <span
            aria-hidden
            className="inline-flex h-3.5 w-3.5 items-center justify-center rounded-full text-[9px] font-bold text-white"
            style={{ backgroundColor: 'var(--status-critical)' }}
          >
            !
          </span>
          Over by {formatMinutes(cell.planned - cell.capacity)}
        </div>
      )}
      {cell.logged > 0 && (
        <div className="text-[11px] text-slate-600 dark:text-slate-400">{hours(cell.logged)}h logged</div>
      )}
    </td>
  );
}

function CapacityEditor({ person }: { person: Person }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(String(person.capacity_minutes / 60));
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.PATCH('/api/v1/users/{user_id}', {
          params: { path: { user_id: person.user_id } },
          body: { capacity_minutes: Math.round(Number(value) * 60) },
        }),
      ),
    onSuccess: () => {
      setEditing(false);
      void queryClient.invalidateQueries({ queryKey: ['workload'] });
    },
  });
  if (!editing)
    return (
      <button
        type="button"
        className="text-xs text-sky-700 hover:underline dark:text-sky-400"
        aria-label={`Change capacity for ${person.name}`}
        onClick={() => setEditing(true)}
      >
        {hours(person.capacity_minutes)}h/day
      </button>
    );
  return (
    <form
      className="flex items-center gap-1"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <Input
        aria-label={`Hours per day for ${person.name}`}
        type="number"
        min={0}
        max={24}
        step={0.5}
        className="w-16 py-0.5"
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
      <GhostButton type="submit" className="px-2 py-0.5">
        Save
      </GhostButton>
      <ErrorText error={save.error} />
    </form>
  );
}

export function WorkloadPage() {
  const { user } = useAuth();
  const isAdmin = user.org_role === 'owner' || user.org_role === 'admin';
  const [start, setStart] = useState(() => mondayOf(todayIso()));
  const [weeks, setWeeks] = useState(4);
  const [projectId, setProjectId] = useState('');
  const [bucket, setBucket] = useState<'week' | 'day'>('week');
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => unwrap(api.GET('/api/v1/projects')) });
  const end = addDays(start, weeks * 7 - 1);
  const workload = useQuery({
    queryKey: ['workload', start, end, projectId, bucket],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/workload', {
          params: { query: { date_from: start, date_to: end, bucket, project_id: projectId || undefined } },
        }),
      ),
  });
  const data = workload.data;
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-bold">Workload</h1>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Remaining estimated work (estimate minus time logged), spread across each task&apos;s dates, against
          each person&apos;s capacity.
        </p>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Project" id="wl-project">
          <Select id="wl-project" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">All projects</option>
            {projects.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.key} — {p.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Starting" id="wl-start">
          <Input
            id="wl-start"
            type="date"
            value={start}
            onChange={(e) => e.target.value && setStart(mondayOf(e.target.value))}
          />
        </Field>
        <Field label="Weeks" id="wl-weeks">
          <Select id="wl-weeks" value={weeks} onChange={(e) => setWeeks(Number(e.target.value))}>
            {[2, 4, 8, 12].map((w) => (
              <option key={w}>{w}</option>
            ))}
          </Select>
        </Field>
        <Field label="Group by" id="wl-bucket">
          <Select id="wl-bucket" value={bucket} onChange={(e) => setBucket(e.target.value as 'week' | 'day')}>
            <option value="week">Week</option>
            <option value="day">Day</option>
          </Select>
        </Field>
      </div>
      <ErrorText error={workload.error} />
      {data && data.users.length === 0 && (
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Nobody has assigned open work in this scope.
        </p>
      )}
      {data && data.users.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Planned hours against capacity per person</caption>
            <thead className="text-xs text-slate-600 dark:text-slate-400">
              <tr>
                <th className="py-1 pr-2 font-medium">Person</th>
                {data.buckets.map((b) => (
                  <th key={b} className="px-1 font-medium whitespace-nowrap">
                    {bucket === 'week' ? `Wk ${shortDate(b)}` : shortDate(b)}
                  </th>
                ))}
                <th className="px-1 font-medium">Not scheduled</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {data.users.map((p) => (
                <tr key={p.user_id}>
                  <th scope="row" className="py-1.5 pr-2 text-left align-top font-normal">
                    <div className="font-medium">{p.name}</div>
                    <div className="text-xs text-slate-600 dark:text-slate-400">
                      {p.utilization !== null ? `${Math.round(p.utilization * 100)}% booked` : 'No capacity'}{' '}
                      · {p.open_tasks} open
                    </div>
                    {isAdmin ? (
                      <CapacityEditor person={p} />
                    ) : (
                      <div className="text-xs text-slate-600 dark:text-slate-400">
                        {hours(p.capacity_minutes)}h/day
                      </div>
                    )}
                  </th>
                  {p.buckets.map((c) => (
                    <LoadCell key={c.start} cell={c} />
                  ))}
                  <td className="px-1 py-1.5 align-top text-xs text-slate-600 dark:text-slate-400">
                    {p.unscheduled_minutes > 0 && <div>{formatMinutes(p.unscheduled_minutes)} undated</div>}
                    {p.overdue_minutes > 0 && <div>{formatMinutes(p.overdue_minutes)} overdue</div>}
                    {p.unestimated_tasks > 0 && <div>{p.unestimated_tasks} without estimate</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
