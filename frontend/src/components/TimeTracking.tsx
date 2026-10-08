import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type FormEvent } from 'react';

import { api, unwrap, type User } from '../api/client';
import { formatMinutes, parseDuration } from '../lib/format';
import { useTimer } from '../lib/timer';
import { ErrorText, GhostButton, Input } from './ui';

function useTick(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [active]);
  return now;
}

function elapsed(startedAt: string, now: number): string {
  const s = Math.max(0, Math.floor((now - Date.parse(startedAt)) / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}:${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

function invalidateTime(queryClient: ReturnType<typeof useQueryClient>) {
  for (const key of ['timer', 'time-entries', 'timesheet', 'time-report', 'workload', 'report']) {
    void queryClient.invalidateQueries({ queryKey: [key] });
  }
}

/** Header pill showing the running timer with a Stop button. */
export function TimerIndicator() {
  const queryClient = useQueryClient();
  const timer = useTimer();
  const now = useTick(!!timer.data);
  const stop = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/timer/stop', { body: {} })),
    onSettled: () => invalidateTime(queryClient),
  });
  if (!timer.data) return null;
  return (
    <div className="flex items-center gap-2 rounded-full border border-slate-300 px-3 py-1 text-sm dark:border-slate-600">
      <span aria-hidden className="h-2 w-2 animate-pulse rounded-full bg-red-600" />
      <span className="font-mono text-xs">{timer.data.task_key}</span>
      <span className="tabular-nums" aria-label="Elapsed time">
        {elapsed(timer.data.started_at, now)}
      </span>
      <button
        type="button"
        className="rounded px-1 text-xs font-medium text-sky-700 hover:underline dark:text-sky-400"
        onClick={() => stop.mutate()}
        disabled={stop.isPending}
      >
        Stop
      </button>
    </div>
  );
}

/** Task drawer section: total logged, entries, quick log form and timer start. */
export function TaskTime({ taskId, taskKey, users }: { taskId: string; taskKey: string; users: User[] }) {
  const queryClient = useQueryClient();
  const names = new Map(users.map((u) => [u.id, u.name]));
  const entries = useQuery({
    queryKey: ['time-entries', 'task', taskId],
    queryFn: () =>
      unwrap(api.GET('/api/v1/time-entries', { params: { query: { task: taskId, limit: 50 } } })),
  });
  const timer = useTimer();
  const [duration, setDuration] = useState('');
  const [note, setNote] = useState('');
  const [invalid, setInvalid] = useState(false);
  const log = useMutation({
    mutationFn: (minutes: number) =>
      unwrap(api.POST('/api/v1/time-entries', { body: { task: taskId, minutes, note } })),
    onSuccess: () => {
      setDuration('');
      setNote('');
      invalidateTime(queryClient);
    },
  });
  const start = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/timer', { body: { task: taskId } })),
    onSettled: () => invalidateTime(queryClient),
  });
  const stop = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/timer/stop', { body: {} })),
    onSettled: () => invalidateTime(queryClient),
  });
  const remove = useMutation({
    mutationFn: (entryId: string) =>
      unwrap(api.DELETE('/api/v1/time-entries/{entry_id}', { params: { path: { entry_id: entryId } } })),
    onSettled: () => invalidateTime(queryClient),
  });
  const total = entries.data?.items.reduce((sum, e) => sum + e.minutes, 0) ?? 0;
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const minutes = parseDuration(duration);
    setInvalid(minutes === null);
    if (minutes !== null) log.mutate(minutes);
  };
  const running = timer.data?.task_id === taskId;
  return (
    <section aria-labelledby="time-h" className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h3 id="time-h" className="text-sm font-semibold">
          Time{' '}
          <span className="font-normal text-slate-600 dark:text-slate-400">
            · {formatMinutes(total)} logged
          </span>
        </h3>
        {!timer.data && (
          <GhostButton
            onClick={() => start.mutate()}
            disabled={start.isPending}
            aria-label={`Start timer on ${taskKey}`}
          >
            ▶ Start timer
          </GhostButton>
        )}
        {running && (
          <GhostButton
            onClick={() => stop.mutate()}
            disabled={stop.isPending}
            aria-label={`Stop timer on ${taskKey}`}
          >
            ■ Stop timer
          </GhostButton>
        )}
        {timer.data && !running && (
          <span className="text-xs text-slate-600 dark:text-slate-400">
            Timer running on {timer.data.task_key}
          </span>
        )}
      </div>
      <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs" htmlFor="time-duration">
          Duration
          <Input
            id="time-duration"
            className="w-28"
            placeholder="1h 30m"
            aria-invalid={invalid}
            value={duration}
            onChange={(e) => setDuration(e.target.value)}
            required
          />
        </label>
        <label className="flex flex-1 flex-col gap-1 text-xs" htmlFor="time-note">
          Note
          <Input id="time-note" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
        </label>
        <GhostButton type="submit" disabled={log.isPending}>
          Log time
        </GhostButton>
      </form>
      {invalid && (
        <p role="alert" className="text-xs text-red-700 dark:text-red-400">
          Enter a duration like 45m, 1h 30m, 1.5h or 1:30.
        </p>
      )}
      <ul className="flex flex-col gap-1 text-xs">
        {entries.data?.items.map((e) => (
          <li key={e.id} className="flex items-center justify-between gap-2">
            <span>
              <strong className="tabular-nums">{formatMinutes(e.minutes)}</strong> ·{' '}
              {names.get(e.user_id) ?? 'Someone'} · {e.spent_on}
              {e.note && <span className="text-slate-600 dark:text-slate-400"> — {e.note}</span>}
            </span>
            <button
              type="button"
              className="text-slate-500 hover:text-red-700"
              aria-label={`Delete ${formatMinutes(e.minutes)} logged on ${e.spent_on}`}
              onClick={() => remove.mutate(e.id)}
            >
              ✕
            </button>
          </li>
        ))}
      </ul>
      <ErrorText error={log.error ?? start.error ?? stop.error ?? remove.error} />
    </section>
  );
}
