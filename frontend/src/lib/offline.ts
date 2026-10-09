import { useSyncExternalStore } from 'react';

import type { Task, User } from '../api/client';

/**
 * A small copy of your own work kept on this device, so a phone can show "My tasks" without a
 * connection, and ticks made offline sync later. It holds only your profile, your open tasks
 * (key, title, due date, status, project) and ticks not yet sent; signing out removes all of it.
 */
const ME = 'glasshaus.offline.me.v1';
const tasksKey = (userId: string) => `glasshaus.offline.tasks.v1.${userId}`;
const queueKey = (userId: string) => `glasshaus.offline.done.v1.${userId}`;

export type OfflineTask = Pick<Task, 'id' | 'key' | 'title' | 'due_date' | 'priority'> & {
  status: { name: string; category: string };
};
export type Snapshot = { savedAt: string; items: OfflineTask[] };
export type QueuedDone = { id: string; key: string; at: string };

function read<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage full or blocked: offline copies are a convenience, never required.
  }
}

export function rememberUser(user: User): void {
  write(ME, user);
}

export function rememberedUser(): User | null {
  return read<User>(ME);
}

export function saveMyTasks(userId: string, items: Task[]): void {
  write(tasksKey(userId), {
    savedAt: new Date().toISOString(),
    items: items.map((t) => ({
      id: t.id,
      key: t.key,
      title: t.title,
      due_date: t.due_date,
      priority: t.priority,
      status: { name: t.status.name, category: t.status.category },
    })),
  } satisfies Snapshot);
}

export function loadMyTasks(userId: string): Snapshot | null {
  return read<Snapshot>(tasksKey(userId));
}

export function queuedDone(userId: string): QueuedDone[] {
  return read<QueuedDone[]>(queueKey(userId)) ?? [];
}

export function queueDone(userId: string, task: { id: string; key: string }): void {
  const queue = queuedDone(userId).filter((q) => q.id !== task.id);
  write(queueKey(userId), [...queue, { id: task.id, key: task.key, at: new Date().toISOString() }]);
}

export function setQueue(userId: string, queue: QueuedDone[]): void {
  if (queue.length) write(queueKey(userId), queue);
  else forgetKey(queueKey(userId));
}

function forgetKey(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // ignore
  }
}

/** Remove everything this device kept for offline use (on sign-out). */
export function forgetOffline(userId?: string): void {
  forgetKey(ME);
  if (userId) {
    forgetKey(tasksKey(userId));
    forgetKey(queueKey(userId));
  }
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener('online', onChange);
  window.addEventListener('offline', onChange);
  return () => {
    window.removeEventListener('online', onChange);
    window.removeEventListener('offline', onChange);
  };
}

/** Whether the browser thinks it has a connection (updates on the online/offline events). */
export function useOnline(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => navigator.onLine,
    () => true,
  );
}
