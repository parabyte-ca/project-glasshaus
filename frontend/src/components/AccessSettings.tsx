import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import { api, unwrap, type Schemas } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { Button, ErrorText, Field, GhostButton, Input, Select } from './ui';

type Scope = Schemas['Scope'];

const shortDate = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { dateStyle: 'medium' }) : 'never';

/** Personal API tokens (REST, webhooks, MCP clients without OAuth) and apps connected with OAuth. */
export function AccessSettings() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const isAdmin = user.org_role === 'owner' || user.org_role === 'admin';
  const [name, setName] = useState('');
  const [access, setAccess] = useState<'read' | 'write' | 'admin'>('write');
  const [secret, setSecret] = useState<string | null>(null);

  const tokens = useQuery({ queryKey: ['tokens'], queryFn: () => unwrap(api.GET('/api/v1/tokens')) });
  const apps = useQuery({ queryKey: ['oauth-apps'], queryFn: () => unwrap(api.GET('/api/v1/oauth/apps')) });

  const create = useMutation({
    mutationFn: () => {
      const scopes: Scope[] =
        access === 'admin'
          ? ['admin']
          : access === 'read'
            ? ['read']
            : ['read', 'tasks:write', 'projects:write'];
      return unwrap(api.POST('/api/v1/tokens', { body: { name, scopes, expires_in_days: 90 } }));
    },
    onSuccess: async (created) => {
      setSecret(created.token);
      setName('');
      await queryClient.invalidateQueries({ queryKey: ['tokens'] });
    },
  });
  const revoke = useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE('/api/v1/tokens/{token_id}', { params: { path: { token_id: id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tokens'] }),
  });
  const disconnect = useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE('/api/v1/oauth/apps/{app_id}', { params: { path: { app_id: id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['oauth-apps'] }),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSecret(null);
    create.mutate();
  };
  const active = (tokens.data ?? []).filter((t) => !t.revoked_at);

  return (
    <>
      <section aria-labelledby="tokens-h" className="flex flex-col gap-3">
        <h2 id="tokens-h" className="text-lg font-semibold">
          API tokens
        </h2>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          For scripts, the REST API and AI assistants that connect with a token (see the MCP integration
          guide). Tokens act as you and expire after 90 days.
        </p>
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <Field label="Token name" id="token-name">
            <Input
              id="token-name"
              required
              maxLength={100}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="VS Code Copilot"
            />
          </Field>
          <Field label="Access" id="token-access">
            <Select
              id="token-access"
              value={access}
              onChange={(e) => setAccess(e.target.value as typeof access)}
            >
              <option value="read">Read only</option>
              <option value="write">Read and write</option>
              {isAdmin && <option value="admin">Admin</option>}
            </Select>
          </Field>
          <Button type="submit" disabled={!name.trim() || create.isPending}>
            Create token
          </Button>
        </form>
        <ErrorText error={create.error ?? revoke.error} />
        {secret && (
          <div
            role="status"
            className="rounded border border-amber-400 bg-amber-50 p-3 text-sm dark:bg-amber-950"
          >
            <p className="font-semibold">Copy this token now; it will not be shown again.</p>
            <code className="block break-all select-all">{secret}</code>
          </div>
        )}
        {active.length > 0 && (
          <ul className="divide-y divide-slate-200 text-sm dark:divide-slate-700">
            {active.map((t) => (
              <li key={t.id} className="flex items-center justify-between gap-3 py-2">
                <span>
                  <span className="font-medium">{t.name}</span>{' '}
                  <span className="font-mono text-slate-500 dark:text-slate-400">{t.prefix}…</span>
                  <span className="block text-slate-600 dark:text-slate-400">
                    {t.scopes.join(', ')} · last used {shortDate(t.last_used_at)} · expires{' '}
                    {t.expires_at ? shortDate(t.expires_at) : 'never'}
                  </span>
                </span>
                <GhostButton
                  aria-label={`Revoke ${t.name}`}
                  onClick={() => revoke.mutate(t.id)}
                  disabled={revoke.isPending}
                >
                  Revoke
                </GhostButton>
              </li>
            ))}
          </ul>
        )}
      </section>

      <CalendarFeed />

      <section aria-labelledby="apps-h" className="flex flex-col gap-3">
        <h2 id="apps-h" className="text-lg font-semibold">
          Connected apps
        </h2>
        {apps.data && apps.data.length === 0 && (
          <p className="text-sm text-slate-600 dark:text-slate-400">
            No apps are connected. Apps you approve with OAuth (for example VS Code or Claude) appear here.
          </p>
        )}
        <ErrorText error={apps.error ?? disconnect.error} />
        <ul className="divide-y divide-slate-200 text-sm dark:divide-slate-700">
          {(apps.data ?? []).map((a) => (
            <li key={a.id} className="flex items-center justify-between gap-3 py-2">
              <span>
                <span className="font-medium">{a.client_name}</span>
                <span className="block text-slate-600 dark:text-slate-400">
                  {a.scopes.join(', ')} · connected {shortDate(a.created_at)} · last used{' '}
                  {shortDate(a.last_used_at)}
                </span>
              </span>
              <GhostButton
                aria-label={`Disconnect ${a.client_name}`}
                onClick={() => disconnect.mutate(a.id)}
                disabled={disconnect.isPending}
              >
                Disconnect
              </GhostButton>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

function CalendarFeed() {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState<string | null>(null);
  const feed = useQuery({
    queryKey: ['calendar-feed'],
    queryFn: () => unwrap(api.GET('/api/v1/calendar-feed')),
  });
  const reset = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/calendar-feed')),
    onSuccess: async (data) => {
      setUrl(data.url ?? null);
      await queryClient.invalidateQueries({ queryKey: ['calendar-feed'] });
    },
  });
  const off = useMutation({
    mutationFn: () => unwrap(api.DELETE('/api/v1/calendar-feed')),
    onSuccess: async () => {
      setUrl(null);
      await queryClient.invalidateQueries({ queryKey: ['calendar-feed'] });
    },
  });
  const active = Boolean(feed.data?.created_at);
  return (
    <section aria-labelledby="calendar-h" className="flex flex-col gap-3">
      <h2 id="calendar-h" className="text-lg font-semibold">
        Calendar feed
      </h2>
      <p className="text-sm text-slate-600 dark:text-slate-400">
        Subscribe to your open, dated tasks in Google Calendar, Outlook / Microsoft 365 or Apple Calendar. The
        link is private: anyone with it can see those task titles. Creating a new link turns off the old one.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => reset.mutate()} disabled={reset.isPending}>
          {active ? 'Create a new link' : 'Create calendar link'}
        </Button>
        {active && <GhostButton onClick={() => off.mutate()}>Turn off</GhostButton>}
      </div>
      {url && (
        <div
          role="status"
          className="rounded border border-amber-400 bg-amber-50 p-3 text-sm dark:bg-amber-950"
        >
          <p className="font-semibold">Your calendar link (copy it now; it is shown once)</p>
          <code className="block break-all select-all">{url}</code>
        </div>
      )}
      {active && !url && (
        <p className="text-sm">
          Active since {shortDate(feed.data?.created_at)} · last fetched {shortDate(feed.data?.last_used_at)}
        </p>
      )}
      <ErrorText error={feed.error ?? reset.error ?? off.error} />
    </section>
  );
}
