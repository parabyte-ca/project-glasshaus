import { useState } from 'react';
import { Link, useParams } from 'react-router';

import { Burnup, ProjectHealthCard, StatTile, StatusMix, Throughput } from '../components/ReportWidgets';
import { useReport } from '../lib/reports';
import { ErrorText, Field, Select } from '../components/ui';
import { addDays, todayIso } from '../lib/dates';
import { formatMinutes } from '../lib/format';
import { useProject } from '../lib/useProject';

export function ProjectReportPage() {
  const { projectKey = '' } = useParams();
  const { project, users } = useProject(projectKey);
  const [days, setDays] = useState(30);
  const to = todayIso();
  const from = addDays(to, -(days - 1));
  const report = useReport(project.data?.id ?? '', from, to);
  const names = new Map(users.map((u) => [u.id, u.name]));
  if (!project.data) return <p role="status">Loading…</p>;
  const r = report.data;
  return (
    <div className="flex max-w-5xl flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link
            to={`/projects/${projectKey}`}
            className="text-sm text-sky-700 hover:underline dark:text-sky-400"
          >
            ← {project.data.name}
          </Link>
          <h1 className="text-2xl font-bold">Report</h1>
        </div>
        <div className="flex items-end gap-3">
          <Field label="Range" id="rp-range">
            <Select id="rp-range" value={days} onChange={(e) => setDays(Number(e.target.value))}>
              <option value={14}>Last 14 days</option>
              <option value={30}>Last 30 days</option>
              <option value={90}>Last 90 days</option>
              <option value={180}>Last 180 days</option>
            </Select>
          </Field>
          <a
            className="text-sm text-sky-700 hover:underline dark:text-sky-400"
            href={`/api/v1/projects/${project.data.id}/tasks/export`}
          >
            Export tasks (CSV)
          </a>
        </div>
      </div>
      <ErrorText error={report.error} />
      <section aria-label="Health" className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
        <ProjectHealthCard projectId={project.data.id} />
      </section>
      {r && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile label="Open" value={r.open} />
            <StatTile label="Done" value={r.done} />
            <StatTile label="Overdue" value={r.overdue} />
            <StatTile label="Logged in range" value={formatMinutes(r.logged_minutes)} />
          </div>
          <section aria-labelledby="burnup-h">
            <h2 id="burnup-h" className="mb-1 font-semibold">
              Burn-up
            </h2>
            <Burnup report={r} />
          </section>
          <div className="grid gap-6 md:grid-cols-2">
            <section aria-labelledby="tp-h">
              <h2 id="tp-h" className="mb-1 font-semibold">
                Throughput
              </h2>
              <Throughput report={r} />
            </section>
            <section aria-labelledby="mix-h">
              <h2 id="mix-h" className="mb-1 font-semibold">
                Status mix
              </h2>
              <StatusMix report={r} />
            </section>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <StatTile
              label="Lead time (median)"
              value={r.lead_time_days.median !== null ? `${r.lead_time_days.median}d` : '—'}
              note={
                r.lead_time_days.p85 !== null ? `85% within ${r.lead_time_days.p85}d` : 'No completed tasks'
              }
            />
            <StatTile label="Estimated (completed)" value={formatMinutes(r.estimate_minutes)} />
            <StatTile
              label="Actual (completed)"
              value={formatMinutes(r.actual_minutes)}
              note={
                r.estimate_minutes
                  ? `${Math.round((r.actual_minutes / r.estimate_minutes) * 100)}% of estimate`
                  : undefined
              }
            />
          </div>
          <section aria-labelledby="who-h">
            <h2 id="who-h" className="mb-1 font-semibold">
              Open work by assignee
            </h2>
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-slate-600 dark:text-slate-400">
                <tr>
                  <th className="py-1 font-medium">Assignee</th>
                  <th className="text-right font-medium">Open tasks</th>
                  <th className="text-right font-medium">Remaining estimate</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 tabular-nums dark:divide-slate-800">
                {r.by_assignee.map((a) => (
                  <tr key={a.user_id ?? 'none'}>
                    <td className="py-1">{a.user_id ? (names.get(a.user_id) ?? 'Unknown') : 'Unassigned'}</td>
                    <td className="text-right">{a.open_tasks}</td>
                    <td className="text-right">{formatMinutes(a.remaining_minutes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  );
}
