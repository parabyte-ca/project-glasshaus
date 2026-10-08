import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useSearchParams } from 'react-router';

import { api, unwrap } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { ErrorText, Field, GhostButton, Input, Select } from '../components/ui';
import { addDays, todayIso } from '../lib/dates';
import { formatMinutes, hours, mondayOf, shortDay } from '../lib/format';

function exportUrl(params: Record<string, string | undefined>): string {
  const q = new URLSearchParams(Object.entries(params).filter((e): e is [string, string] => !!e[1]));
  return `/api/v1/time-entries/export?${q.toString()}`;
}

function TimesheetView() {
  const { user } = useAuth();
  const [week, setWeek] = useState(() => mondayOf(todayIso()));
  const [userId, setUserId] = useState(user.id);
  const users = useQuery({
    queryKey: ['users'],
    queryFn: () => unwrap(api.GET('/api/v1/users')),
    enabled: user.org_role !== 'guest',
  });
  const end = addDays(week, 6);
  const sheet = useQuery({
    queryKey: ['timesheet', userId, week],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/timesheets', {
          params: { query: { user_id: userId, date_from: week, date_to: end } },
        }),
      ),
  });
  const s = sheet.data;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3">
        {!!users.data?.length && (
          <Field label="Person" id="ts-user">
            <Select id="ts-user" value={userId} onChange={(e) => setUserId(e.target.value)}>
              {users.data.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <div className="flex items-center gap-1" role="group" aria-label="Week">
          <GhostButton aria-label="Previous week" onClick={() => setWeek(addDays(week, -7))}>
            ←
          </GhostButton>
          <GhostButton onClick={() => setWeek(mondayOf(todayIso()))}>This week</GhostButton>
          <GhostButton aria-label="Next week" onClick={() => setWeek(addDays(week, 7))}>
            →
          </GhostButton>
        </div>
        <p className="text-sm text-slate-600 dark:text-slate-400" aria-live="polite">
          Week of {week}
        </p>
        <a
          className="ml-auto text-sm text-sky-700 hover:underline dark:text-sky-400"
          href={exportUrl({ user_id: userId, date_from: week, date_to: end })}
        >
          Export CSV
        </a>
      </div>
      <ErrorText error={sheet.error} />
      {s && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <caption className="sr-only">Timesheet, hours per task and day</caption>
            <thead className="text-xs text-slate-600 dark:text-slate-400">
              <tr>
                <th className="py-1 font-medium">Task</th>
                {s.days.map((d) => (
                  <th key={d} className="text-right font-medium">
                    {shortDay(d)}
                  </th>
                ))}
                <th className="text-right font-medium">Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 tabular-nums dark:divide-slate-800">
              {s.rows.length === 0 && (
                <tr>
                  <td colSpan={9} className="py-3 text-slate-600 dark:text-slate-400">
                    No time logged this week. Log time from a task, or start a timer.
                  </td>
                </tr>
              )}
              {s.rows.map((r) => (
                <tr key={r.task_id}>
                  <td className="py-1.5">
                    <span className="mr-2 font-mono text-xs">{r.task_key}</span>
                    {r.task_title}
                  </td>
                  {s.days.map((d) => (
                    <td key={d} className="text-right">
                      {r.minutes_by_day[d] ? hours(r.minutes_by_day[d]) : ''}
                    </td>
                  ))}
                  <td className="text-right font-medium">{hours(r.total)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot className="border-t border-slate-300 font-medium tabular-nums dark:border-slate-600">
              <tr>
                <td className="py-1.5">Total (hours)</td>
                {s.days.map((d) => (
                  <td key={d} className="text-right">
                    {s.totals_by_day[d] ? hours(s.totals_by_day[d]) : ''}
                  </td>
                ))}
                <td className="text-right">{hours(s.total)}</td>
              </tr>
            </tfoot>
          </table>
          <p className="mt-2 text-xs text-slate-600 dark:text-slate-400">
            {formatMinutes(s.total)} this week, {formatMinutes(s.billable_total)} billable.
          </p>
        </div>
      )}
    </div>
  );
}

function TeamReport() {
  const [from, setFrom] = useState(() => addDays(todayIso(), -29));
  const [to, setTo] = useState(todayIso);
  const report = useQuery({
    queryKey: ['time-report', from, to],
    queryFn: () =>
      unwrap(api.GET('/api/v1/reports/time', { params: { query: { date_from: from, date_to: to } } })),
  });
  const rows = report.data?.rows ?? [];
  const projects = [...new Map(rows.map((r) => [r.project_id, r.project_key])).entries()].sort((a, b) =>
    a[1].localeCompare(b[1]),
  );
  const people = [...new Map(rows.map((r) => [r.user_id, r.user_name])).entries()];
  const cell = new Map(rows.map((r) => [`${r.user_id}:${r.project_id}`, r.minutes]));
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="From" id="tr-from">
          <Input id="tr-from" type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} />
        </Field>
        <Field label="To" id="tr-to">
          <Input id="tr-to" type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
        </Field>
        <a
          className="ml-auto text-sm text-sky-700 hover:underline dark:text-sky-400"
          href={exportUrl({ date_from: from, date_to: to })}
        >
          Export CSV
        </a>
      </div>
      <ErrorText error={report.error} />
      {report.data && rows.length === 0 && (
        <p className="text-sm text-slate-600 dark:text-slate-400">No time logged in this range.</p>
      )}
      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Hours per person and project</caption>
            <thead className="text-xs text-slate-600 dark:text-slate-400">
              <tr>
                <th className="py-1 font-medium">Person</th>
                {projects.map(([id, key]) => (
                  <th key={id} className="text-right font-mono font-medium">
                    {key}
                  </th>
                ))}
                <th className="text-right font-medium">Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 tabular-nums dark:divide-slate-800">
              {people.map(([uid, name]) => {
                const total = projects.reduce((sum, [pid]) => sum + (cell.get(`${uid}:${pid}`) ?? 0), 0);
                return (
                  <tr key={uid}>
                    <td className="py-1.5">{name}</td>
                    {projects.map(([pid]) => (
                      <td key={pid} className="text-right">
                        {cell.get(`${uid}:${pid}`) ? hours(cell.get(`${uid}:${pid}`)!) : ''}
                      </td>
                    ))}
                    <td className="text-right font-medium">{hours(total)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-slate-600 dark:text-slate-400">
            Hours. {formatMinutes(report.data?.total ?? 0)} in total.
          </p>
        </div>
      )}
    </div>
  );
}

export function TimePage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') === 'team' ? 'team' : 'mine';
  return (
    <div className="flex max-w-5xl flex-col gap-4">
      <h1 className="text-2xl font-bold">Time</h1>
      <div
        role="tablist"
        aria-label="Time views"
        className="flex gap-1 border-b border-slate-200 dark:border-slate-800"
      >
        {(
          [
            ['mine', 'Timesheet'],
            ['team', 'Team report'],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            role="tab"
            type="button"
            aria-selected={tab === id}
            onClick={() => setParams(id === 'mine' ? {} : { tab: id }, { replace: true })}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${
              tab === id
                ? 'border-sky-700 font-medium text-sky-800 dark:border-sky-400 dark:text-sky-300'
                : 'border-transparent text-slate-600 dark:text-slate-400'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      <div role="tabpanel">{tab === 'mine' ? <TimesheetView /> : <TeamReport />}</div>
    </div>
  );
}
