import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';

import { api, ApiError, unwrap } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { ErrorText } from '../components/ui';
import {
  loadMyTasks,
  queueDone,
  queuedDone,
  saveMyTasks,
  setQueue,
  type OfflineTask,
  useOnline,
} from '../lib/offline';
import { usePageTitle } from '../lib/pageTitle';
import { toast } from '../lib/toast';

const OPEN = ['backlog', 'todo', 'in_progress'] as const;

function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function groups(items: OfflineTask[]): [string, OfflineTask[]][] {
  const today = isoDay(new Date());
  const week = isoDay(new Date(Date.now() + 7 * 86_400_000));
  const out: Record<string, OfflineTask[]> = {
    Overdue: [],
    Today: [],
    'Next 7 days': [],
    Later: [],
    'No due date': [],
  };
  for (const t of items) {
    const due = t.due_date;
    const bucket = !due
      ? 'No due date'
      : due < today
        ? 'Overdue'
        : due === today
          ? 'Today'
          : due <= week
            ? 'Next 7 days'
            : 'Later';
    out[bucket]!.push(t);
  }
  return Object.entries(out).filter(([, list]) => list.length > 0);
}

const slug = (heading: string) => heading.toLowerCase().replace(/\W+/g, '-');
const projectOf = (key: string) => key.slice(0, key.lastIndexOf('-'));

/**
 * Your open tasks across projects, soonest due first. A copy stays on this device so the list
 * opens without a connection; ticks made offline are kept here and sent when you are back online.
 */
export function MyTasksPage() {
  usePageTitle('My tasks');
  const { user, offline: serverUnreachable } = useAuth();
  const online = useOnline() && !serverUnreachable;
  const queryClient = useQueryClient();
  const tasks = useQuery({
    queryKey: ['my-tasks', user.id],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/tasks', {
          params: {
            query: {
              assignee_ids: [user.id],
              status_categories: [...OPEN],
              sort: 'due_date',
              limit: 200,
            },
          },
        }),
      ),
  });
  useEffect(() => {
    if (tasks.data) saveMyTasks(user.id, tasks.data.items);
  }, [tasks.data, user.id]);
  const [queue, setQueued] = useState(() => queuedDone(user.id));

  const complete = useMutation({
    mutationFn: (t: { id: string; key: string }) =>
      unwrap(api.POST('/api/v1/tasks/{ref}/complete', { params: { path: { ref: t.id } } })),
    onSuccess: async (task) => {
      toast(`Done: ${task.key}`);
      await queryClient.invalidateQueries({ queryKey: ['my-tasks', user.id] });
    },
  });

  // Back online: send the ticks made offline, oldest first.
  const flushing = useRef(false);
  useEffect(() => {
    if (!online || flushing.current || queuedDone(user.id).length === 0) return;
    flushing.current = true;
    void (async () => {
      const left = [];
      let sent = 0;
      for (const item of queuedDone(user.id)) {
        try {
          await unwrap(api.POST('/api/v1/tasks/{ref}/complete', { params: { path: { ref: item.id } } }));
          sent += 1;
        } catch (err) {
          // Gone or no longer yours to change: drop it and say so; a network error keeps it queued.
          if (err instanceof ApiError) toast(`${item.key} could not be marked done: ${err.message}`, 'error');
          else left.push(item);
        }
      }
      setQueue(user.id, left);
      setQueued(left);
      flushing.current = false;
      if (sent) toast(`Synced ${sent} task${sent === 1 ? '' : 's'} marked done while offline`);
      await queryClient.invalidateQueries({ queryKey: ['my-tasks', user.id] });
    })();
  }, [online, user.id, queryClient]);

  const snapshot = tasks.data ? null : loadMyTasks(user.id);
  const items: OfflineTask[] = (tasks.data?.items ?? snapshot?.items ?? []).filter(
    (t) => !queue.some((q) => q.id === t.id),
  );

  const markDone = (t: OfflineTask) => {
    if (online) {
      complete.mutate(t);
      return;
    }
    queueDone(user.id, t);
    setQueued(queuedDone(user.id));
    toast(`${t.key} will be marked done when you're back online`);
  };

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold">My tasks</h1>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Your open tasks in every project, soonest due first.
        </p>
      </div>
      {!online && (
        <p role="status" className="rounded-lg border border-amber-400 p-3 text-sm">
          <strong>You’re offline.</strong>{' '}
          {snapshot
            ? `Showing your tasks as of ${new Date(snapshot.savedAt).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}.`
            : 'Open this page once while online to keep a copy on this device.'}{' '}
          Tasks you tick are marked done when you’re back online
          {queue.length > 0 ? ` (${queue.length} waiting)` : ''}.
        </p>
      )}
      {online && <ErrorText error={tasks.error ?? complete.error} />}
      {tasks.isPending && online && <p role="status">Loading…</p>}
      {items.length === 0 && (tasks.data || snapshot) && (
        <p className="text-slate-600 dark:text-slate-400">Nothing open. Nice work.</p>
      )}
      {groups(items).map(([heading, list]) => (
        <section key={heading} aria-labelledby={`my-${slug(heading)}`} className="flex flex-col gap-2">
          <h2 id={`my-${slug(heading)}`} className="text-lg font-semibold">
            {heading}{' '}
            <span className="text-sm font-normal text-slate-600 dark:text-slate-400">({list.length})</span>
          </h2>
          <ul className="flex flex-col divide-y divide-slate-200 rounded-lg border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
            {list.map((t) => (
              <li key={t.id} className="flex items-center gap-3 px-3 py-2">
                <input
                  type="checkbox"
                  className="size-5 shrink-0"
                  aria-label={`Mark ${t.key} done`}
                  checked={false}
                  disabled={complete.isPending && complete.variables?.id === t.id}
                  onChange={() => markDone(t)}
                />
                <div className="min-w-0 flex-1">
                  {online ? (
                    <Link
                      to={`/projects/${projectOf(t.key)}?task=${t.id}`}
                      className="block truncate font-medium hover:underline"
                    >
                      {t.title}
                    </Link>
                  ) : (
                    <span className="block truncate font-medium">{t.title}</span>
                  )}
                  <span className="text-xs text-slate-600 dark:text-slate-400">
                    <span className="font-mono">{t.key}</span> · {t.status.name}
                    {t.priority === 'urgent' || t.priority === 'high' ? ` · ${t.priority}` : ''}
                  </span>
                </div>
                {t.due_date && (
                  <span
                    className={`shrink-0 text-sm tabular-nums ${heading === 'Overdue' ? 'font-medium text-red-700 dark:text-red-400' : ''}`}
                  >
                    {new Date(`${t.due_date}T00:00:00`).toLocaleDateString(undefined, {
                      month: 'short',
                      day: 'numeric',
                    })}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
