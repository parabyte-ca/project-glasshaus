import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';

import { api, unwrap, type Task } from '../api/client';

interface LiveEvent {
  type: string;
  aggregate_type?: string;
  aggregate_id?: string;
  project_id?: string | null;
}

/**
 * An edit to one task refreshes just that task in the open lists (one small request) instead of
 * refetching every list of the project (up to 500 tasks each).
 */
export function patchable(event: LiveEvent): boolean {
  return event.type === 'task.updated' && !!event.aggregate_id && !!event.project_id;
}

/** Map a live event to the query keys that may now be stale. */
export function keysFor(event: LiveEvent): unknown[][] {
  if (event.type === 'notification.created') return [['notifications']];
  const keys: unknown[][] = [];
  const [kind] = event.type.split('.');
  // Lists don't show comments, so comment events leave them alone.
  if (kind === 'task' && !patchable(event)) keys.push(['tasks', event.project_id]);
  if (kind === 'task' || kind === 'comment') {
    keys.push(['my-tasks']);
    if (event.aggregate_id) {
      keys.push(['task', event.aggregate_id], ['comments', event.aggregate_id]);
      keys.push(['activity', 'task', event.aggregate_id]);
    }
  }
  if (kind === 'field') keys.push(['fields', event.project_id], ['tasks', event.project_id]);
  if (kind === 'view') keys.push(['views', event.project_id]);
  if (kind === 'project' || kind === 'status') keys.push(['projects'], ['project']);
  // An import adds or changes many tasks at once without an event for each.
  if (event.type === 'project.imported') keys.push(['tasks', event.project_id], ['my-tasks']);
  // Getting-started milestones tick from new tasks, assignments, due dates and project members.
  if (kind === 'task' || kind === 'project') keys.push(['onboarding']);
  return keys;
}

export const BATCH_MS = 400;
/** Above this many edited tasks in one burst, refetching the lists is cheaper than patching. */
export const PATCH_LIMIT = 20;
const LIST_LIMIT = 500; // the project page's page size

type TaskPage = { items: Task[] } & Record<string, unknown>;
type Fetch = (taskId: string) => Promise<Task>;

const fetchTask: Fetch = (taskId) =>
  unwrap(api.GET('/api/v1/tasks/{ref}', { params: { path: { ref: taskId } } }));

/**
 * Collects stale query keys and edited tasks from a burst of events, then refreshes each once. Bulk
 * edits and imports otherwise refetch the same 500-row task list once per event.
 */
export class InvalidationBatcher {
  private pending = new Map<string, unknown[]>();
  private patches = new Map<string, Set<string>>(); // project id -> edited task ids
  private timer: ReturnType<typeof setTimeout> | undefined;

  constructor(
    private readonly queryClient: QueryClient,
    private readonly delay = BATCH_MS,
    private readonly fetch: Fetch = fetchTask,
  ) {}

  add(keys: unknown[][], patch?: { projectId: string; taskId: string }) {
    for (const key of keys) this.pending.set(JSON.stringify(key), key);
    if (patch) {
      const ids = this.patches.get(patch.projectId) ?? new Set<string>();
      ids.add(patch.taskId);
      this.patches.set(patch.projectId, ids);
    }
    if ((this.pending.size > 0 || this.patches.size > 0) && this.timer === undefined) {
      this.timer = setTimeout(() => this.flush(), this.delay);
    }
  }

  flush() {
    clearTimeout(this.timer);
    this.timer = undefined;
    const keys = [...this.pending.values()];
    const patches = [...this.patches.entries()];
    this.pending.clear();
    this.patches.clear();
    for (const queryKey of keys) this.invalidate(queryKey);
    for (const [projectId, ids] of patches) {
      if (ids.size > PATCH_LIMIT) this.invalidate(['tasks', projectId]);
      else for (const id of ids) void this.patch(projectId, id);
    }
  }

  private invalidate(queryKey: unknown[], exact = false) {
    // A refetch already in flight is fresh enough; don't cancel and restart it.
    void this.queryClient.invalidateQueries({ queryKey, exact }, { cancelRefetch: false });
  }

  /** Swap the fresh task into each open list of its project; refetch only lists it may have left. */
  private async patch(projectId: string, taskId: string) {
    const lists = this.queryClient.getQueriesData<TaskPage>({ queryKey: ['tasks', projectId] });
    if (lists.length === 0) return;
    let task: Task;
    try {
      task = await this.fetch(taskId);
    } catch {
      this.invalidate(['tasks', projectId]); // deleted, moved away or no longer visible
      return;
    }
    for (const [key, page] of lists) {
      const config = key[2];
      if (typeof config !== 'object' || config === null || !page || !Array.isArray(page.items)) {
        // Not a view's task list (the timeline's schedule, warnings, baselines…): recompute it.
        this.invalidate([...key], true);
        continue;
      }
      const { filters } = config as { filters?: Record<string, unknown> };
      const filtered = Object.values(filters ?? {}).some((v) => v !== undefined && v !== null && v !== '');
      const present = page.items.some((t) => t.id === task.id);
      if (task.project_id !== projectId || filtered || (!present && page.items.length < LIST_LIMIT)) {
        // It may have entered or left this list (a filter, another project): let the server decide.
        this.invalidate([...key], true);
      } else if (present) {
        this.queryClient.setQueryData<TaskPage>(key, {
          ...page,
          items: page.items.map((t) => (t.id === task.id ? task : t)),
        });
      }
    }
  }

  dispose() {
    clearTimeout(this.timer);
    this.timer = undefined;
    this.pending.clear();
    this.patches.clear();
  }
}

/** Keep queries fresh from the server's WebSocket feed (ids only; data is refetched through the API). */
export function useLiveUpdates(enabled = true) {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!enabled || typeof WebSocket === 'undefined') return;
    let socket: WebSocket | null = null;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let ping: ReturnType<typeof setInterval> | undefined;
    let closed = false;
    const batcher = new InvalidationBatcher(queryClient);

    const connect = () => {
      const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
      socket = new WebSocket(`${scheme}://${window.location.host}/api/v1/ws`);
      socket.onopen = () => {
        retry = 0;
        ping = setInterval(() => socket?.readyState === WebSocket.OPEN && socket.send('ping'), 25_000);
      };
      socket.onmessage = (msg) => {
        const event = JSON.parse(String(msg.data)) as LiveEvent;
        if (event.type === 'pong') return;
        batcher.add(
          keysFor(event),
          patchable(event) ? { projectId: event.project_id!, taskId: event.aggregate_id! } : undefined,
        );
      };
      socket.onclose = () => {
        clearInterval(ping);
        if (closed) return;
        retry += 1;
        timer = setTimeout(connect, Math.min(30_000, 1000 * 2 ** retry));
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      clearInterval(ping);
      batcher.dispose();
      socket?.close();
    };
  }, [enabled, queryClient]);
}
