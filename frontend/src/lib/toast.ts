import { useSyncExternalStore } from 'react';

export type Toast = { id: number; message: string; tone: 'info' | 'error' };

let toasts: Toast[] = [];
let nextId = 1;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

/** Show a short message ("Rule deleted", "Copied") that screen readers announce; errors stay longer. */
export function toast(message: string, tone: Toast['tone'] = 'info') {
  const item = { id: nextId++, message, tone };
  toasts = [...toasts.slice(-3), item];
  emit();
  setTimeout(() => dismissToast(item.id), tone === 'error' ? 8000 : 4000);
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
