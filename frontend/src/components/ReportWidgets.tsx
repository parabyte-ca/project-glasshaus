import { type ProjectReport } from '../api/client';
import { useHealth } from '../lib/reports';
import { formatMinutes, shortDate } from '../lib/format';
import { BarChart, HealthBadge, LineChart, ProgressBar } from './charts';
import { ErrorText } from './ui';

export function StatTile({ label, value, note }: { label: string; value: string | number; note?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
      <p className="text-xs text-slate-600 dark:text-slate-400">{label}</p>
      <p className="text-2xl font-semibold">{value}</p>
      {note && <p className="text-xs text-slate-600 dark:text-slate-400">{note}</p>}
    </div>
  );
}

export function Burnup({ report }: { report: ProjectReport }) {
  return (
    <LineChart
      title="Burn-up: scope and completed tasks per day"
      labels={report.burnup.map((p) => p.day)}
      formatLabel={shortDate}
      series={[
        { name: 'Scope', color: 'var(--series-1)', values: report.burnup.map((p) => p.scope) },
        { name: 'Done', color: 'var(--series-2)', values: report.burnup.map((p) => p.done) },
      ]}
    />
  );
}

export function Throughput({ report }: { report: ProjectReport }) {
  return (
    <BarChart
      title="Tasks completed per week"
      name="Completed"
      labels={report.throughput.map((p) => p.week)}
      formatLabel={(d) => `Wk ${shortDate(d)}`}
      values={report.throughput.map((p) => p.completed)}
    />
  );
}

export function StatusMix({ report }: { report: ProjectReport }) {
  const max = Math.max(1, ...report.by_status.map((s) => s.count));
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">Tasks per status</caption>
      <tbody>
        {report.by_status.map((s) => (
          <tr key={s.status_id}>
            <th scope="row" className="w-32 py-1 pr-2 text-left font-normal">
              <span className="inline-flex items-center gap-1.5">
                <span aria-hidden className="h-2 w-2 rounded-full" style={{ backgroundColor: s.color }} />
                {s.name}
              </span>
            </th>
            <td className="py-1">
              <div className="flex items-center gap-2">
                <div className="h-2 flex-1" aria-hidden>
                  <div
                    className="h-2 rounded-r"
                    style={{ width: `${(s.count / max) * 100}%`, backgroundColor: 'var(--series-1)' }}
                  />
                </div>
                <span className="w-8 text-right tabular-nums">{s.count}</span>
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function ProjectHealthCard({ projectId }: { projectId: string }) {
  const health = useHealth(projectId);
  if (health.error) return <ErrorText error={health.error} />;
  if (!health.data) return <p role="status">Loading…</p>;
  const h = health.data;
  return (
    <div className="flex flex-col gap-2 text-sm">
      <div className="flex items-center justify-between">
        <span className="font-medium">
          <span className="mr-1 font-mono text-xs">{h.key}</span>
          {h.name}
        </span>
        <HealthBadge health={h.health} />
      </div>
      <ProgressBar value={h.progress} label={`${h.key} progress`} />
      <p className="text-xs text-slate-600 dark:text-slate-400">
        {h.done}/{h.total} done · {h.overdue} overdue
        {h.finish && ` · finish ${shortDate(h.finish)}`}
        {h.slip_days > 0 && ` · ${h.slip_days}d behind baseline`} · {formatMinutes(h.logged_minutes)} logged
      </p>
    </div>
  );
}
