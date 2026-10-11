import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router';

import { api, unwrap, type Schemas } from '../api/client';
import { Dialog } from '../components/Dialog';
import { LoadError } from '../components/PageState';
import { GhostButton, linkClass } from '../components/ui';
import { hours, shortDate } from '../lib/format';
import { notablePriority } from '../lib/labels';
import { usePageTitle } from '../lib/pageTitle';

type Member = Schemas['TeamMember'];
type TeamTask = Schemas['TeamTask'];

const UNKNOWN: [string, string] = ['Health not set', 'var(--color-slate-400)'];
const HEALTH: Record<string, [string, string]> = {
  on_track: ['On track', 'var(--status-good)'],
  at_risk: ['At risk', 'var(--status-warning)'],
  off_track: ['Off track', 'var(--status-critical)'],
};

function Stat({ label, value, alert = false }: { label: string; value: string | number; alert?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-slate-600 dark:text-slate-400">{label}</dt>
      <dd className={`text-lg font-semibold tabular-nums ${alert ? 'text-red-700 dark:text-red-400' : ''}`}>
        {value}
      </dd>
    </div>
  );
}

function TaskList({ tasks }: { tasks: TeamTask[] }) {
  return (
    <ul className="flex flex-col divide-y divide-slate-200 dark:divide-slate-800">
      {tasks.map((t) => (
        <li key={t.id} className="flex items-baseline gap-3 py-2 text-sm">
          <div className="min-w-0 flex-1">
            <Link to={`/projects/${t.project_key}?task=${t.id}`} className={`${linkClass} block truncate`}>
              {t.title}
            </Link>
            <span className="text-xs text-slate-600 dark:text-slate-400">
              <span className="font-mono">{t.key}</span> · {t.project_name} · {t.status}
              {notablePriority(t.priority)}
            </span>
          </div>
          {t.completed_at ? (
            <span className="shrink-0 tabular-nums">Done {shortDate(t.completed_at.slice(0, 10))}</span>
          ) : (
            t.due_date && <span className="shrink-0 tabular-nums">Due {shortDate(t.due_date)}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

function PersonTasks({ person, onClose }: { person: Member; onClose: () => void }) {
  const [done, setDone] = useState(false);
  const tasks = useQuery({
    queryKey: ['team-tasks', person.id, done],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/team/{person_id}/tasks', {
          params: { path: { person_id: person.id }, query: { done } },
        }),
      ),
  });
  return (
    <Dialog
      title={`${person.name}: ${done ? 'finished in the last 30 days' : 'open work'}`}
      onClose={onClose}
      wide
    >
      <div className="mb-3 flex gap-2">
        <GhostButton aria-pressed={!done} onClick={() => setDone(false)}>
          Open
        </GhostButton>
        <GhostButton aria-pressed={done} onClick={() => setDone(true)}>
          Finished
        </GhostButton>
      </div>
      {tasks.isPending && <p role="status">Loading…</p>}
      {tasks.error && (
        <LoadError inline error={tasks.error} what="these tasks" onRetry={() => void tasks.refetch()} />
      )}
      {tasks.data && (
        <>
          {tasks.data.tasks.length === 0 ? (
            <p className="text-slate-600 dark:text-slate-400">Nothing here.</p>
          ) : (
            <TaskList tasks={tasks.data.tasks} />
          )}
          {tasks.data.hidden > 0 && (
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
              {tasks.data.hidden} more in projects you can’t open.
            </p>
          )}
        </>
      )}
    </Dialog>
  );
}

function PersonCard({ m, onOpen }: { m: Member; onOpen: () => void }) {
  const capacity = m.capacity_week;
  return (
    <li className="flex flex-col gap-3 rounded-lg border border-slate-200 p-4 dark:border-slate-800">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold">{m.name}</h2>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            {[m.job_title, m.department].filter(Boolean).join(' · ') || m.email}
            {m.level > 1 &&
              ` · ${m.level === 2 ? 'reports to one of your reports' : `${m.level} levels down`}`}
          </p>
        </div>
        <GhostButton onClick={onOpen} aria-label={`See ${m.name}'s tasks`}>
          See tasks
        </GhostButton>
      </div>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Open" value={m.open} />
        <Stat label="Overdue" value={m.overdue} alert={m.overdue > 0} />
        <Stat label="Due this week" value={m.due_this_week} />
        <Stat label="In progress" value={m.in_progress} />
        <Stat
          label="Logged this week"
          value={`${hours(m.logged_this_week)}${capacity ? ` / ${hours(capacity)}` : ''}h`}
        />
        <Stat label="Last week" value={`${hours(m.logged_last_week)}h`} />
        <Stat label="Done in 7 days" value={m.completed_last_7_days} />
        <Stat label="Stale (5+ days)" value={m.stale} alert={m.stale > 0} />
      </dl>
      {m.projects.length > 0 && (
        <div>
          <h3 className="mb-1 text-sm font-semibold">Projects</h3>
          <ul className="flex flex-wrap gap-2 text-sm">
            {m.projects.map((p) => {
              const [label, colour] = (p.health && HEALTH[p.health]) || UNKNOWN;
              return (
                <li
                  key={p.id}
                  className="flex items-center gap-1.5 rounded border border-slate-200 px-2 py-0.5 dark:border-slate-700"
                >
                  <span aria-hidden className="size-2 rounded-full" style={{ backgroundColor: colour }} />
                  {p.key && p.visible ? (
                    <Link to={`/projects/${p.key}`} className={linkClass}>
                      {p.name}
                    </Link>
                  ) : (
                    <span>{p.name ?? 'A project you can’t open'}</span>
                  )}
                  <span className="text-slate-600 dark:text-slate-400">
                    {p.open_tasks} open · {label}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {m.recent.length > 0 && (
        <div>
          <h3 className="mb-1 text-sm font-semibold">Finished recently</h3>
          <TaskList tasks={m.recent} />
        </div>
      )}
    </li>
  );
}

/** Managers: the people who report to you, with their work, time and projects. */
export function TeamPage() {
  usePageTitle('My team');
  const [everyone, setEveryone] = useState(false);
  const [open, setOpen] = useState<Member | null>(null);
  const team = useQuery({
    queryKey: ['team', everyone],
    queryFn: () => unwrap(api.GET('/api/v1/team', { params: { query: { everyone } } })),
    placeholderData: keepPreviousData, // keep the list on screen while the switch loads
  });
  return (
    <div className="flex max-w-5xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold">My team</h1>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          The people who report to you in your organization’s directory.
          {team.data?.visibility === 'shared'
            ? ' You see their work in projects you can open; elsewhere, counts only.'
            : ' You see their work in every project. Opening someone’s tasks is recorded in the audit log.'}
        </p>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={everyone} onChange={(e) => setEveryone(e.target.checked)} />
        Include everyone below me, not only direct reports
      </label>
      {team.isPending && <p role="status">Loading…</p>}
      {team.error && <LoadError error={team.error} what="your team" onRetry={() => void team.refetch()} />}
      {team.data && team.data.people.length === 0 && (
        <p className="text-slate-600 dark:text-slate-400">
          Nobody reports to you yet. Glasshaus learns who reports to whom from your organization’s directory;
          if this looks wrong, ask your administrator.
        </p>
      )}
      {team.data && team.data.people.length > 0 && (
        <ul className="flex flex-col gap-4" aria-label="Team members">
          {team.data.people.map((m) => (
            <PersonCard key={m.id} m={m} onOpen={() => setOpen(m)} />
          ))}
        </ul>
      )}
      {open && <PersonTasks person={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
