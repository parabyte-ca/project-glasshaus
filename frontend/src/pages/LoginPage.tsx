import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router';

import { api, unwrap } from '../api/client';
import { Button, ErrorText, Field, Input } from '../components/ui';

export function LoginPage() {
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [organization, setOrganization] = useState('');
  const login = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/auth/login', { body: { email, password, organization: organization || null } }),
      ),
    onSuccess: (user) => queryClient.setQueryData(['me'], user),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate();
  };

  return (
    <main
      id="main"
      className="flex min-h-screen items-center justify-center bg-slate-50 px-4 text-slate-900 dark:bg-slate-950 dark:text-slate-100"
    >
      <form
        onSubmit={submit}
        className="flex w-full max-w-sm flex-col gap-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900"
      >
        <h1 className="text-xl font-semibold">Sign in to Project Glasshaus</h1>
        {params.get('signedOut') === 'password' && (
          <p
            role="status"
            className="rounded-md bg-emerald-50 p-2 text-sm text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
          >
            Password changed. Sign in with your new password.
          </p>
        )}
        <Field label="Email" id="email">
          <Input
            id="email"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>
        <Field label="Password" id="password">
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <Field label="Organization (optional)" id="organization">
          <Input id="organization" value={organization} onChange={(e) => setOrganization(e.target.value)} />
        </Field>
        <ErrorText error={login.error} />
        <Button type="submit" disabled={login.isPending}>
          {login.isPending ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>
    </main>
  );
}
