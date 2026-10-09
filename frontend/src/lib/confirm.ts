import { createContext, use, type ReactNode } from 'react';

export type ConfirmOptions = {
  title: string;
  body?: ReactNode;
  /** The action's name on the button ("Delete", "Remove", "Make admin"); never just "OK". */
  confirmLabel: string;
  danger?: boolean;
};

export const ConfirmContext = createContext<((options: ConfirmOptions) => Promise<boolean>) | null>(null);

/** Ask before a destructive or far-reaching change: `if (await confirm({...})) remove.mutate()`. */
export function useConfirm() {
  const confirm = use(ConfirmContext);
  // Outside the provider (isolated component tests) fall back to the browser's prompt.
  return confirm ?? ((o: ConfirmOptions) => Promise.resolve(window.confirm(o.title)));
}
