import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router';

import { api, unwrap } from '../api/client';
import { Button, ErrorText, Field, Input } from '../components/ui';
import { usePageTitle } from '../lib/pageTitle';

export function LoginPage() {
  usePageTitle('Sign in');
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

  const providers = useQuery({
    queryKey: ['sso-providers', 'public', organization],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/auth/sso/providers', { params: { query: { organization: organization || null } } }),
      ),
    retry: false,
  });
  const ssoError = params.get('sso_error');
  const next = (() => {
    const search = new URLSearchParams(window.location.search);
    search.delete('sso_error');
    const query = search.toString();
    return window.location.pathname + (query ? `?${query}` : '');
  })();

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
        {ssoError && (
          <p role="alert" className="text-sm text-red-700 dark:text-red-400">
            Single sign-on failed: {ssoError}
          </p>
        )}
        {(providers.data ?? []).map((p) => (
          <a
            key={p.slug}
            href={`${p.start_url}?next=${encodeURIComponent(next)}`}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-center text-sm font-medium hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800"
          >
            Sign in with {p.name}
          </a>
        ))}
        {(providers.data?.length ?? 0) > 0 && (
          <p className="text-center text-xs text-slate-500 dark:text-slate-400">or use your password</p>
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
