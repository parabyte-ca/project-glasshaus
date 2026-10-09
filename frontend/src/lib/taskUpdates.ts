import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api, unwrap, type Task } from '../api/client';

export type TaskPatch = Record<string, unknown>;

// One request at a time per task, each sent with the newest version we know of. Without this, quick
// successive edits (timeline arrow keys, a drop followed by a select) race and the later ones fail
// with a version conflict.
const chains = new Map<string, Promise<unknown>>();
const versions = new Map<string, number>();
// Edits in flight per task (the optimistic hook refetches once the last one settles).
const pending = new Map<string, number>();

export function patchTask(task: Pick<Task, 'id' | 'version'>, patch: TaskPatch): Promise<Task> {
  const previous = chains.get(task.id) ?? Promise.resolve();
  const run = previous
    .catch(() => undefined)
    .then(async () => {
      const expected_version = Math.max(versions.get(task.id) ?? 0, task.version);
      const updated = await unwrap(
        api.PATCH('/api/v1/tasks/{ref}', {
          params: { path: { ref: task.id } },
          body: { ...patch, expected_version },
        }),
      );
      versions.set(task.id, Math.max(versions.get(task.id) ?? 0, updated.version));
      return updated;
    });
  chains.set(task.id, run);
  void run
    .catch(() => undefined)
    .finally(() => {
      if (chains.get(task.id) === run) chains.delete(task.id);
    });
  return run;
}

/** Test hook: forget queued requests and known versions. */
export function resetTaskUpdates() {
  chains.clear();
  versions.clear();
  pending.clear();
}

/** The task with a patch applied locally (status and custom fields need the project to resolve). */
export function applyPatch(task: Task, patch: TaskPatch, statuses: Task['status'][] = []): Task {
  const next = { ...task } as Record<string, unknown>;
  for (const [key, value] of Object.entries(patch)) {
    if (key === 'custom_fields') {
      next.custom_fields = { ...task.custom_fields, ...(value as Record<string, unknown>) };
    } else if (key === 'status_id') {
      const status = statuses.find((s) => s.id === value);
      if (status) next.status = status;
    } else {
      next[key] = value;
    }
  }
  return next as Task;
}

type TaskPage = { items: Task[] } & Record<string, unknown>;
type Snapshot = [readonly unknown[], unknown][];

/**
 * Update a task optimistically, in the project's lists and in the open task drawer: the change shows
 * at once, is rolled back if the server refuses it, and everything is refetched once the task's last
 * queued edit has settled.
 */
export function useTaskUpdate(projectId: string | undefined, statuses: Task['status'][] = []) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ task, patch }: { task: Task; patch: TaskPatch }) => patchTask(task, patch),
    onMutate: async ({ task, patch }): Promise<{ snapshot: Snapshot }> => {
      pending.set(task.id, (pending.get(task.id) ?? 0) + 1);
      const lists = { queryKey: ['tasks', projectId] };
      const single = (key: readonly unknown[]) =>
        key[0] === 'task' && (key[1] === task.id || key[1] === task.key);
      await Promise.all([
        queryClient.cancelQueries(lists),
        queryClient.cancelQueries({ predicate: (q) => single(q.queryKey) }),
      ]);
      const snapshot: Snapshot = [
        ...queryClient.getQueriesData(lists),
        ...queryClient.getQueriesData({ predicate: (q) => single(q.queryKey) }),
      ];
      const apply = (t: Task) => (t.id === task.id ? applyPatch(t, patch, statuses) : t);
      queryClient.setQueriesData<TaskPage>(lists, (page) =>
        page && Array.isArray(page.items) ? { ...page, items: page.items.map(apply) } : page,
      );
      queryClient.setQueriesData<Task>({ predicate: (q) => single(q.queryKey) }, (t) => t && apply(t));
      return { snapshot };
    },
    onError: (_error, _vars, context) => {
      for (const [key, data] of context?.snapshot ?? []) queryClient.setQueryData(key, data);
    },
    onSettled: (updated, _error, { task }) => {
      const left = (pending.get(task.id) ?? 1) - 1;
      if (left > 0) {
        pending.set(task.id, left);
        return; // a later edit to this task is still on its way
      }
      pending.delete(task.id);
      if (updated) {
        queryClient.setQueryData(['task', updated.key], updated);
        queryClient.setQueryData(['task', updated.id], updated);
      }
      void queryClient.invalidateQueries({ queryKey: ['tasks', projectId] });
      void queryClient.invalidateQueries({ queryKey: ['task', task.key] });
      void queryClient.invalidateQueries({ queryKey: ['activity', 'task', task.id] });
    },
  });
}
