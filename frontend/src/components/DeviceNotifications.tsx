import { useMutation } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { api, unwrap } from '../api/client';
import { pushState, turnOff, turnOn, type PushState } from '../lib/push';
import { toast } from '../lib/toast';
import { Button, ErrorText, GhostButton } from './ui';

const TEXT: Record<PushState, string> = {
  unsupported: 'This browser cannot show Glasshaus notifications.',
  'needs-install':
    'On iPhone and iPad, first add Glasshaus to your Home Screen (Share → Add to Home Screen), then open it from there and turn notifications on.',
  blocked:
    'Notifications are blocked for this site. Allow them in your browser or phone settings, then try again.',
  off: 'Get a notification on this device when someone mentions you, assigns you a task, or a report alert goes off.',
  on: 'This device gets your Glasshaus notifications.',
};

/** Turn phone or desktop notifications on or off for this device. */
export function DeviceNotifications() {
  const [state, setState] = useState<PushState | null>(null);
  useEffect(() => {
    void pushState().then(setState);
  }, []);
  const change = useMutation({
    mutationFn: (on: boolean) => (on ? turnOn() : turnOff()),
    onSuccess: (next) => setState(next),
  });
  const test = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/push/test')),
    onSuccess: () => toast('Test sent; it should arrive in a few seconds'),
  });
  if (state === null) return null;
  return (
    <section aria-labelledby="device-notifications-h" className="flex max-w-2xl flex-col gap-3">
      <h2 id="device-notifications-h" className="text-lg font-semibold">
        Notifications on this device
      </h2>
      <p className="text-sm text-slate-600 dark:text-slate-400">{TEXT[state]}</p>
      <div className="flex flex-wrap gap-2">
        {state === 'off' || state === 'blocked' ? (
          <Button onClick={() => change.mutate(true)} disabled={change.isPending}>
            Turn on notifications
          </Button>
        ) : null}
        {state === 'on' && (
          <>
            <GhostButton onClick={() => test.mutate()} disabled={test.isPending}>
              Send a test
            </GhostButton>
            <GhostButton onClick={() => change.mutate(false)} disabled={change.isPending}>
              Turn off on this device
            </GhostButton>
          </>
        )}
      </div>
      <ErrorText error={change.error ?? test.error} />
    </section>
  );
}
