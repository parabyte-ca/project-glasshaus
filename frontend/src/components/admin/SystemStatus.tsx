import { useQuery } from '@tanstack/react-query';

import { api, unwrap } from '../../api/client';
import { ErrorText, GhostButton } from '../ui';
import { Section } from './common';
import { dateTime } from './format';

type State = 'ok' | 'warning' | 'critical' | 'unknown';

const LOOK: Record<State, { label: string; icon: string; tone: string }> = {
  ok: {
    label: 'OK',
    icon: '✓',
    tone: 'border-green-300 text-green-800 dark:border-green-800 dark:text-green-400',
  },
  warning: {
    label: 'Needs attention',
    icon: '!',
    tone: 'border-amber-300 text-amber-800 dark:border-amber-700 dark:text-amber-300',
  },
  critical: {
    label: 'Problem',
    icon: '✕',
    tone: 'border-red-300 text-red-700 dark:border-red-800 dark:text-red-400',
  },
  unknown: {
    label: 'Unknown',
    icon: '?',
    tone: 'border-slate-300 text-slate-700 dark:border-slate-600 dark:text-slate-300',
  },
};

const SUMMARY: Record<State, string> = {
  ok: 'Everything is working.',
  warning: 'Something needs attention.',
  critical: 'Something is not working.',
  unknown: 'Some checks could not run.',
};

/** Health of everything Glasshaus depends on, refreshed every minute while open. */
export function SystemStatus() {
  const status = useQuery({
    queryKey: ['admin-status'],
    queryFn: () => unwrap(api.GET('/api/v1/admin/status')),
    refetchInterval: 60_000,
  });
  const s = status.data;
  return (
    <Section
      title="System status"
      intro={
        <>
          Glasshaus checks the database, Redis, the background worker, live updates, integrations, backups and
          disk space every five minutes, and tells owners and admins (in the app, and by email when it is set
          up) when something needs attention. Prometheus can scrape the same numbers from{' '}
          <code>/metrics</code>.
        </>
      }
    >
      <ErrorText error={status.error} />
      {s && (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <p
              role="status"
              className={`rounded border px-3 py-1 text-sm font-semibold ${LOOK[s.overall].tone}`}
            >
              <span aria-hidden="true">{LOOK[s.overall].icon}</span> {SUMMARY[s.overall]}
            </p>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              Version {s.version}, checked {dateTime(s.checked_at)}
            </p>
            <GhostButton
              onClick={() => void status.refetch()}
              disabled={status.isFetching}
              aria-busy={status.isFetching}
            >
              {status.isFetching ? 'Checking…' : 'Check now'}
            </GhostButton>
          </div>
          <ul aria-label="Checks" className="flex max-w-3xl flex-col gap-2">
            {s.checks.map((c) => (
              <li
                key={c.key}
                className="flex items-start gap-3 rounded-lg border border-slate-200 p-3 dark:border-slate-800"
              >
                <span
                  className={`mt-0.5 inline-flex min-w-28 justify-center rounded border px-2 text-xs font-semibold ${LOOK[c.state].tone}`}
                >
                  <span aria-hidden="true">{LOOK[c.state].icon}&nbsp;</span>
                  {LOOK[c.state].label}
                </span>
                <div className="text-sm">
                  <p className="font-medium">{c.name}</p>
                  <p className="text-slate-600 dark:text-slate-400">{c.message}</p>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </Section>
  );
}
