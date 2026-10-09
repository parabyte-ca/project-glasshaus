import { useCallback, useState, type ReactNode } from 'react';

import { ConfirmContext, type ConfirmOptions } from '../lib/confirm';
import { Dialog } from './Dialog';
import { Button, GhostButton } from './ui';

type Pending = ConfirmOptions & { resolve: (ok: boolean) => void };

/** One accessible confirmation dialog for the app (instead of window.confirm). */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<Pending | null>(null);
  const confirm = useCallback(
    (options: ConfirmOptions) =>
      new Promise<boolean>((resolve) => {
        setPending((previous) => {
          previous?.resolve(false);
          return { ...options, resolve };
        });
      }),
    [],
  );
  const finish = (ok: boolean) => {
    pending?.resolve(ok);
    setPending(null);
  };
  return (
    <ConfirmContext value={confirm}>
      {children}
      {pending && (
        <Dialog title={pending.title} onClose={() => finish(false)}>
          {pending.body && <div className="text-sm text-slate-700 dark:text-slate-300">{pending.body}</div>}
          <div className="flex justify-end gap-2">
            <GhostButton data-autofocus onClick={() => finish(false)}>
              Cancel
            </GhostButton>
            <Button danger={pending.danger} onClick={() => finish(true)}>
              {pending.confirmLabel}
            </Button>
          </div>
        </Dialog>
      )}
    </ConfirmContext>
  );
}
