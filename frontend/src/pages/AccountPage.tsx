import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';

import { api, unwrap } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { AccessSettings } from '../components/AccessSettings';
import { DeviceNotifications } from '../components/DeviceNotifications';
import { Button, ErrorText, Field, Input } from '../components/ui';
import { usePageTitle } from '../lib/pageTitle';

export const MIN_PASSWORD_LENGTH = 12;

export function AccountPage() {
  usePageTitle('Account');
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [problem, setProblem] = useState<string | null>(null);

  const change = useMutation({
    mutationFn: () =>
      unwrap(api.POST('/api/v1/auth/password', { body: { current_password: current, new_password: next } })),
    onSuccess: async () => {
      // The server ends every session after a password change: drop cached data, then re-check the
      // session (now 401) so the app falls back to the sign-in screen.
      await navigate('/?signedOut=password');
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'me' });
      await queryClient.resetQueries({ queryKey: ['me'] });
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (next.length < MIN_PASSWORD_LENGTH) {
      setProblem(`The new password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
    } else if (next !== confirm) {
      setProblem('The new passwords do not match.');
    } else if (next === current) {
      setProblem('Choose a password different from the current one.');
    } else {
      setProblem(null);
      change.mutate();
    }
  };

  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <h1 className="text-2xl font-bold">Account</h1>
      <dl className="grid grid-cols-[6rem_1fr] gap-y-1 text-sm">
        <dt className="text-slate-600 dark:text-slate-400">Name</dt>
        <dd>{user.name}</dd>
        <dt className="text-slate-600 dark:text-slate-400">Email</dt>
        <dd>{user.email}</dd>
        <dt className="text-slate-600 dark:text-slate-400">Role</dt>
        <dd className="capitalize">{user.org_role}</dd>
      </dl>

      <section aria-labelledby="password-h" className="flex flex-col gap-3">
        <h2 id="password-h" className="text-lg font-semibold">
          Change password
        </h2>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          At least {MIN_PASSWORD_LENGTH} characters. You will be signed out everywhere and asked to sign in
          again.
        </p>
        <form onSubmit={submit} className="flex max-w-md flex-col gap-3" noValidate>
          <Field label="Current password" id="current-password">
            <Input
              id="current-password"
              type="password"
              autoComplete="current-password"
              required
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
          </Field>
          <Field label="New password" id="new-password">
            <Input
              id="new-password"
              type="password"
              autoComplete="new-password"
              required
              minLength={MIN_PASSWORD_LENGTH}
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
          </Field>
          <Field label="Confirm new password" id="confirm-password">
            <Input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              required
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </Field>
          <ErrorText error={problem ?? change.error} />
          <Button
            type="submit"
            disabled={change.isPending || !current || !next || !confirm}
            className="self-start"
          >
            {change.isPending ? 'Changing…' : 'Change password'}
          </Button>
        </form>
      </section>

      <DeviceNotifications />
      <AccessSettings />
    </div>
  );
}
