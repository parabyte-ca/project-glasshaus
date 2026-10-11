import { useQuery } from '@tanstack/react-query';

import { api, unwrap } from '../../api/client';
import { ErrorText } from '../ui';
import { Section } from './common';
import { dateTime, table, td, th } from './format';

const size = (bytes: number) =>
  bytes >= 1024 ** 3
    ? `${(bytes / 1024 ** 3).toFixed(1)} GB`
    : bytes >= 1024 ** 2
      ? `${(bytes / 1024 ** 2).toFixed(1)} MB`
      : `${Math.max(1, Math.round(bytes / 1024))} KB`;

/** Backups and the last restore drill, read from the backup folder. */
export function Backups() {
  const status = useQuery({
    queryKey: ['admin-backups'],
    queryFn: () => unwrap(api.GET('/api/v1/admin/backups')),
  });
  const s = status.data;
  return (
    <Section
      title="Backups"
      intro={
        <>
          The backup service saves the database on a schedule and, every few days, restores the newest backup
          into a scratch database to prove it works (a restore drill). Owners and admins get a notification
          once a day while something needs attention. To restore, see the backup guide.
        </>
      }
    >
      <ErrorText error={status.error} />
      {s && !s.available && (
        <p
          role="note"
          className="max-w-3xl rounded border border-slate-300 p-3 text-sm dark:border-slate-600"
        >
          The backup folder is not visible to Glasshaus on this server, so backup health cannot be shown.
        </p>
      )}
      {s?.available && (
        <>
          {s.problems.length > 0 ? (
            <div
              role="alert"
              className="max-w-3xl rounded border border-red-300 p-3 text-sm dark:border-red-800"
            >
              <p className="font-semibold text-red-700 dark:text-red-400">Needs attention</p>
              <ul className="list-disc pl-5">
                {s.problems.map((p) => (
                  <li key={p.code}>{p.message}</li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="flex items-center gap-1 text-sm font-medium text-green-800 dark:text-green-400">
              <span aria-hidden="true">✓</span> Backups are up to date and the last restore drill passed.
            </p>
          )}
          <dl className="grid max-w-3xl grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="font-medium">Newest backup</dt>
            <dd>
              {s.latest[0] ? `${dateTime(s.latest[0].created_at)} (${size(s.latest[0].bytes)})` : 'None yet'}
            </dd>
            <dt className="font-medium">Backups kept</dt>
            <dd>
              {s.count} ({size(s.total_bytes)}), every {s.interval_hours} hours
            </dd>
            <dt className="font-medium">Last restore drill</dt>
            <dd>
              {s.drill
                ? `${s.drill.ok ? 'Passed' : 'Failed'} ${dateTime(s.drill.finished_at)} — ${s.drill.dump}, ${s.drill.tables} tables, ${s.drill.rows.users ?? 0} people, ${s.drill.rows.projects ?? 0} projects, ${s.drill.rows.tasks ?? 0} tasks, ${s.drill.seconds} s`
                : s.drill_days > 0
                  ? `None yet (runs every ${s.drill_days} days after a backup)`
                  : 'Turned off'}
            </dd>
          </dl>
          {s.latest[0] && !s.latest[0].encrypted && (
            <p className="text-sm text-amber-800 dark:text-amber-300">
              The newest backup is not encrypted. Run <code>./update.sh</code> to create a backup key
              (GLASSHAUS_BACKUP_KEY in .env), then keep a copy of the key somewhere safe.
            </p>
          )}
          {s.latest.length > 0 && (
            <table className={`${table} max-w-3xl`}>
              <caption className="sr-only">Newest backups</caption>
              <thead>
                <tr>
                  <th scope="col" className={th}>
                    File
                  </th>
                  <th scope="col" className={th}>
                    Saved
                  </th>
                  <th scope="col" className={th}>
                    Protection
                  </th>
                  <th scope="col" className={`${th} text-right`}>
                    Size
                  </th>
                </tr>
              </thead>
              <tbody>
                {s.latest.map((f) => (
                  <tr key={f.name}>
                    <td className={`${td} break-all`}>{f.name}</td>
                    <td className={td}>{dateTime(f.created_at)}</td>
                    <td className={td}>
                      {[f.encrypted ? 'Encrypted' : 'Not encrypted', f.checksum ? 'checksum' : null]
                        .filter(Boolean)
                        .join(', ')}
                    </td>
                    <td className={`${td} text-right tabular-nums`}>{size(f.bytes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </Section>
  );
}
