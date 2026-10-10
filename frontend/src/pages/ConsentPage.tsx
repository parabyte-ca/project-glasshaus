import { useMutation, useQuery } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router';

import { api, unwrap } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { Button, ErrorText, GhostButton } from '../components/ui';
import { usePageTitle } from '../lib/pageTitle';

/** OAuth consent for MCP clients (VS Code, Claude, Copilot): the MCP server's /authorize sends the
 * browser here; approving issues a one-time code and returns the browser to the client. */
export function ConsentPage() {
  usePageTitle('Authorize an app');
  const { user } = useAuth();
  const [params] = useSearchParams();
  const requestId = params.get('request') ?? '';
  const [unchecked, setUnchecked] = useState<Set<string>>(new Set());

  const request = useQuery({
    queryKey: ['oauth-request', requestId],
    queryFn: () =>
      unwrap(api.GET('/api/v1/oauth/requests/{request_id}', { params: { path: { request_id: requestId } } })),
    enabled: requestId !== '',
    retry: false,
  });
  const decide = useMutation({
    mutationFn: (approve: boolean) =>
      unwrap(
        api.POST('/api/v1/oauth/requests/{request_id}', {
          params: { path: { request_id: requestId } },
          body: {
            approve,
            scopes: approve ? (request.data?.scopes ?? []).filter((s) => !unchecked.has(s)) : null,
          },
        }),
      ),
    onSuccess: (result) => {
      // Only web or app addresses; never script URLs (javascript:, data:).
      const { protocol } = new URL(result.redirect_to, window.location.origin);
      if (['javascript:', 'data:', 'vbscript:', 'blob:', 'file:'].includes(protocol)) return;
      window.location.assign(result.redirect_to);
    },
  });

  const toggle = (scope: string) =>
    setUnchecked((prev) => {
      const next = new Set(prev);
      if (next.has(scope)) next.delete(scope);
      else next.add(scope);
      return next;
    });

  const shell = (body: ReactNode) => (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-5 p-6">
      <p className="text-sm font-semibold text-slate-500 dark:text-slate-400">Project Glasshaus</p>
      {body}
    </main>
  );

  if (!requestId) return shell(<p role="alert">This link is missing its authorization request.</p>);
  if (request.isPending) return shell(<p role="status">Loading…</p>);
  if (request.isError) return shell(<ErrorText error={request.error} />);

  const req = request.data;
  const granted = req.scopes.filter((s) => !unchecked.has(s));
  return shell(
    <>
      <h1 className="text-2xl font-bold">
        Allow <span className="break-all">{req.client_name}</span> to use your account?
      </h1>
      <p className="text-sm text-slate-600 dark:text-slate-400">
        Signed in as {user.email}. After you allow it, you will be returned to{' '}
        <span className="font-mono break-all">{req.redirect_host}</span>. It acts as you, with only the
        permissions below, until you disconnect it on your Account page.
      </p>
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 font-semibold">Permissions</legend>
        {req.scopes.map((scope) => (
          <div key={scope} className="flex items-start gap-2 text-sm">
            <input
              id={`scope-${scope}`}
              type="checkbox"
              className="mt-1"
              checked={!unchecked.has(scope)}
              onChange={() => toggle(scope)}
            />
            <label htmlFor={`scope-${scope}`}>
              <span className="font-mono">{scope}</span>
              <span className="block text-slate-600 dark:text-slate-400">{req.scope_labels[scope]}</span>
            </label>
          </div>
        ))}
      </fieldset>
      <p className="text-xs text-slate-600 dark:text-slate-400">
        Only allow apps you started yourself. Your project and organization roles still apply.
      </p>
      <ErrorText error={decide.error} />
      <div className="flex gap-3">
        <Button onClick={() => decide.mutate(true)} disabled={decide.isPending || granted.length === 0}>
          Allow
        </Button>
        <GhostButton onClick={() => decide.mutate(false)} disabled={decide.isPending}>
          Deny
        </GhostButton>
      </div>
    </>,
  );
}
