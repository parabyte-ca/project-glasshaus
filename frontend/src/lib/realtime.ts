import { useQueryClient } from '@tanstack/react-query';
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
  const keys: unknown[][] = [['activity']];
  const [kind] = event.type.split('.');
  if (kind === 'task' || kind === 'comment') {
    keys.push(['tasks', event.project_id]);
    if (event.aggregate_id) keys.push(['task', event.aggregate_id], ['comments', event.aggregate_id]);
  }
  if (kind === 'field') keys.push(['fields', event.project_id], ['tasks', event.project_id]);
  if (kind === 'view') keys.push(['views', event.project_id]);
  if (kind === 'project' || kind === 'status') keys.push(['projects'], ['project']);
  return keys;
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
        for (const queryKey of keysFor(event)) void queryClient.invalidateQueries({ queryKey });
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
      socket?.close();
    };
  }, [enabled, queryClient]);
}
