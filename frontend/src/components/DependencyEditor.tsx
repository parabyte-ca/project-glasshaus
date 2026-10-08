import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import { api, unwrap, type DependencyType, type Task } from '../api/client';
import { ErrorText, GhostButton, Input, Select } from './ui';

const TYPES: { value: DependencyType; label: string }[] = [
  { value: 'fs', label: 'Finish → start' },
  { value: 'ss', label: 'Start → start' },
  { value: 'ff', label: 'Finish → finish' },
  { value: 'sf', label: 'Start → finish' },
];

export function DependencyEditor({ task, canEdit }: { task: Task; canEdit: boolean }) {
  const queryClient = useQueryClient();
  const [predecessor, setPredecessor] = useState('');
  const [type, setType] = useState<DependencyType>('fs');
  const [lag, setLag] = useState('0');
  const deps = useQuery({
    queryKey: ['task', task.id, 'dependencies'],
    queryFn: () =>
      unwrap(api.GET('/api/v1/tasks/{ref}/dependencies', { params: { path: { ref: task.id } } })),
  });
  const candidates = useQuery({
    queryKey: ['tasks', task.project_id, 'all-for-deps'],
    enabled: canEdit,
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/tasks', {
          params: { query: { project_id: task.project_id, limit: 500, sort: 'number' } },
        }),
      ),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['task'] });
    void queryClient.invalidateQueries({ queryKey: ['tasks', task.project_id] });
  };
  const add = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/dependencies', {
          body: { predecessor, successor: task.id, type, lag_days: Number(lag) || 0 },
        }),
      ),
    onSuccess: () => {
      setPredecessor('');
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE('/api/v1/dependencies/{dependency_id}', { params: { path: { dependency_id: id } } })),
    onSettled: refresh,
  });
  const label = (t: DependencyType, days: number) =>
    `${TYPES.find((x) => x.value === t)?.label}${days ? `, ${days > 0 ? '+' : ''}${days}d` : ''}`;

  const linked = new Set([
    task.id,
    ...(deps.data?.predecessors.map((d) => d.predecessor_id) ?? []),
    ...(deps.data?.successors.map((d) => d.successor_id) ?? []),
  ]);
  return (
    <section aria-labelledby="deps-h" className="flex flex-col gap-2 text-sm">
      <h3 id="deps-h" className="font-semibold">
        Dependencies
      </h3>
      <ul className="flex flex-col gap-1">
        {deps.data?.predecessors.map((d) => (
          <li key={d.id} className="flex items-center justify-between gap-2">
            <span>
              Waits for <span className="font-mono text-xs">{d.predecessor_key}</span> {d.predecessor_title}{' '}
              <span className="text-slate-500 dark:text-slate-400">({label(d.type, d.lag_days)})</span>
            </span>
            {canEdit && (
              <GhostButton
                aria-label={`Remove dependency on ${d.predecessor_key}`}
                onClick={() => remove.mutate(d.id)}
              >
                Remove
              </GhostButton>
            )}
          </li>
        ))}
        {deps.data?.successors.map((d) => (
          <li key={d.id}>
            Blocks <span className="font-mono text-xs">{d.successor_key}</span> {d.successor_title}{' '}
            <span className="text-slate-500 dark:text-slate-400">({label(d.type, d.lag_days)})</span>
          </li>
        ))}
        {deps.data && deps.data.predecessors.length + deps.data.successors.length === 0 && (
          <li className="text-slate-500 dark:text-slate-400">No dependencies.</li>
        )}
      </ul>
      {canEdit && (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            if (predecessor) add.mutate();
          }}
        >
          <Select
            aria-label="Waits for task"
            value={predecessor}
            onChange={(e) => setPredecessor(e.target.value)}
          >
            <option value="">Waits for…</option>
            {candidates.data?.items
              .filter((t) => !linked.has(t.id))
              .map((t) => (
                <option key={t.id} value={t.id}>
                  {t.key} {t.title}
                </option>
              ))}
          </Select>
          <Select
            aria-label="Dependency type"
            value={type}
            onChange={(e) => setType(e.target.value as DependencyType)}
          >
            {TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </Select>
          <Input
            aria-label="Lag in days (negative for lead)"
            type="number"
            className="w-20"
            value={lag}
            onChange={(e) => setLag(e.target.value)}
          />
          <GhostButton type="submit" disabled={!predecessor || add.isPending}>
            Add
          </GhostButton>
        </form>
      )}
      <ErrorText error={add.error ?? remove.error} />
      {add.data && add.data.rescheduled.length > 0 && (
        <p role="status" className="text-xs text-slate-600 dark:text-slate-400">
          Auto-scheduled: {add.data.rescheduled.map((m) => `${m.key} +${m.days}d`).join(', ')}
        </p>
      )}
    </section>
  );
}
