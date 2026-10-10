import { useSyncExternalStore } from 'react';

export type ToastAction = { label: string; run: () => void };
export type Toast = { id: number; message: string; tone: 'info' | 'error'; action?: ToastAction };

let toasts: Toast[] = [];
let nextId = 1;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

/**
 * Show a short message ("Rule deleted", "Copied") that screen readers announce. Errors stay until
 * dismissed (people need time to read them); a message with an action (Undo, Retry) stays 10 seconds.
 */
export function toast(message: string, tone: Toast['tone'] = 'info', action?: ToastAction) {
  const item: Toast = { id: nextId++, message, tone, action };
  toasts = [...toasts.slice(-3), item];
  emit();
  if (tone !== 'error') setTimeout(() => dismissToast(item.id), action ? 10_000 : 4000);
  return item.id;
}

export function dismissToast(id: number) {
  if (!toasts.some((t) => t.id === id)) return;
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}

export function useToasts(): Toast[] {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => toasts,
  );
}
