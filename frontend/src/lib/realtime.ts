import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';

interface LiveEvent {
  type: string;
  aggregate_type?: string;
  aggregate_id?: string;
  project_id?: string | null;
}

/** Map a live event to the query keys that may now be stale. */
export function keysFor(event: LiveEvent): unknown[][] {
  if (event.type === 'notification.created') return [['notifications']];
  const keys: unknown[][] = [];
  const [kind] = event.type.split('.');
  if (kind === 'task' || kind === 'comment') {
    keys.push(['tasks', event.project_id]);
    if (event.aggregate_id) {
      keys.push(['task', event.aggregate_id], ['comments', event.aggregate_id]);
      keys.push(['activity', 'task', event.aggregate_id]);
    }
  }
  if (kind === 'field') keys.push(['fields', event.project_id], ['tasks', event.project_id]);
  if (kind === 'view') keys.push(['views', event.project_id]);
  if (kind === 'project' || kind === 'status') keys.push(['projects'], ['project']);
  return keys;
}

export const BATCH_MS = 400;

/**
 * Collects stale query keys from a burst of events and invalidates each one once. Bulk edits and
 * imports otherwise refetch the same 500-row task list once per event.
 */
export class InvalidationBatcher {
  private pending = new Map<string, unknown[]>();
  private timer: ReturnType<typeof setTimeout> | undefined;

  constructor(
    private readonly queryClient: QueryClient,
    private readonly delay = BATCH_MS,
  ) {}

  add(keys: unknown[][]) {
    for (const key of keys) this.pending.set(JSON.stringify(key), key);
    if (this.pending.size > 0 && this.timer === undefined) {
      this.timer = setTimeout(() => this.flush(), this.delay);
    }
  }

  flush() {
    clearTimeout(this.timer);
    this.timer = undefined;
    const keys = [...this.pending.values()];
    this.pending.clear();
    for (const queryKey of keys) {
      // A refetch already in flight is fresh enough; don't cancel and restart it.
      void this.queryClient.invalidateQueries({ queryKey }, { cancelRefetch: false });
    }
  }

  dispose() {
    clearTimeout(this.timer);
    this.timer = undefined;
    this.pending.clear();
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
        batcher.add(keysFor(event));
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
