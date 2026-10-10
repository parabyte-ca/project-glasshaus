import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api, unwrap } from '../../api/client';
import { Button, ErrorText, Field, GhostButton, Input } from '../ui';
import { Copyable, SecretOnce, Section } from './common';
import { dateTime, table, td, th } from './format';
import { useConfirm } from '../../lib/confirm';

export function Provisioning() {
  return (
    <div className="flex flex-col gap-8">
      <ScimTokens />
      <DirectorySync />
      <ManagerVisibility />
    </div>
  );
}

function DirectorySync() {
  const queryClient = useQueryClient();
  const sync = useQuery({
    queryKey: ['directory-sync'],
    queryFn: () => unwrap(api.GET('/api/v1/admin/directory-sync')),
  });
  const [form, setForm] = useState<{ directory_id: string; client_id: string; secret: string } | null>(null);
  const v = form ?? {
    directory_id: sync.data?.directory_id ?? '',
    client_id: sync.data?.client_id ?? '',
    secret: '',
  };
  const save = useMutation({
    mutationFn: (enabled: boolean) =>
      unwrap(
        api.PUT('/api/v1/admin/directory-sync', {
          body: {
            enabled,
            directory_id: v.directory_id,
            client_id: v.client_id,
            ...(v.secret ? { client_secret: v.secret } : {}),
          },
        }),
      ),
    onSuccess: (data) => {
      queryClient.setQueryData(['directory-sync'], data);
      setForm(null);
    },
  });
  const run = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/admin/directory-sync/run')),
    onSuccess: async (data) => {
      queryClient.setQueryData(['directory-sync'], data);
      await queryClient.invalidateQueries({ queryKey: ['users'] });
    },
  });
  const d = sync.data;
  const result = d?.last_result ?? {};
  return (
    <Section
      title="Managers from Microsoft Entra ID"
      intro="My team shows managers the people who report to them. If your identity provider sends managers over SCIM (Entra ID does by default), nothing more is needed. Otherwise, sync them nightly from Microsoft Graph: register an app in Entra ID with the User.Read.All application permission (admin consent) and enter it here. People are matched by email; SCIM wins where it sends a manager."
    >
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(d?.enabled ?? false);
        }}
      >
        <Field label="Directory (tenant) ID or domain" id="graph-dir">
          <Input
            id="graph-dir"
            value={v.directory_id}
            onChange={(e) => setForm({ ...v, directory_id: e.target.value })}
            placeholder="contoso.onmicrosoft.com"
          />
        </Field>
        <Field label="Application (client) ID" id="graph-client">
          <Input
            id="graph-client"
            value={v.client_id}
            onChange={(e) => setForm({ ...v, client_id: e.target.value })}
          />
        </Field>
        <Field
          label={d?.client_secret ? 'Client secret (saved; type to replace)' : 'Client secret'}
          id="graph-secret"
        >
          <Input
            id="graph-secret"
            type="password"
            autoComplete="off"
            value={v.secret}
            onChange={(e) => setForm({ ...v, secret: e.target.value })}
          />
        </Field>
        <Button type="submit" disabled={save.isPending || !form}>
          Save
        </Button>
      </form>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={d?.enabled ?? false}
            disabled={save.isPending || !d}
            onChange={(e) => save.mutate(e.target.checked)}
          />
          Sync every night
        </label>
        <GhostButton
          onClick={() => run.mutate()}
          disabled={run.isPending || !d?.client_secret}
          aria-describedby="graph-status"
        >
          {run.isPending ? 'Syncing…' : 'Sync now'}
        </GhostButton>
      </div>
      <p id="graph-status" role="status" className="text-sm">
        {d?.last_run_at
          ? d.last_error
            ? `Last sync ${dateTime(d.last_run_at)} failed: ${d.last_error}`
            : `Last sync ${dateTime(d.last_run_at)}: ${result.matched ?? 0} people matched, ${result.managers ?? 0} managers changed, ${result.cleared ?? 0} cleared, ${result.skipped ?? 0} left to SCIM.`
          : 'Not synced yet.'}
      </p>
      <ErrorText error={sync.error ?? save.error ?? run.error} />
    </Section>
  );
}

function ManagerVisibility() {
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: ['org-settings'],
    queryFn: () => unwrap(api.GET('/api/v1/admin/settings')),
  });
  const save = useMutation({
    mutationFn: (manager_visibility: 'all' | 'shared') =>
      unwrap(api.PATCH('/api/v1/admin/settings', { body: { manager_visibility } })),
    onSuccess: (data) => queryClient.setQueryData(['org-settings'], data),
  });
  const value = settings.data?.manager_visibility ?? 'shared';
  return (
    <Section
      title="What managers see on My team"
      intro="Opening a report's task list is recorded in the audit log (team.tasks_viewed)."
    >
      <fieldset className="flex flex-col gap-2 text-sm">
        <legend className="sr-only">What managers see</legend>
        <label className="flex items-center gap-2">
          <input
            type="radio"
            name="manager-visibility"
            checked={value === 'shared'}
            disabled={!settings.data || save.isPending}
            onChange={() => save.mutate('shared')}
          />
          Only in projects the manager can open (elsewhere, counts only; recommended)
        </label>
        <label className="flex items-center gap-2">
          <input
            type="radio"
            name="manager-visibility"
            checked={value === 'all'}
            disabled={!settings.data || save.isPending}
            onChange={async () =>
              (await confirm({
                title: 'Show managers their reports’ work in every project?',
                body: 'Managers will see task titles in projects they are not members of. Each look is recorded in the audit log.',
                confirmLabel: 'Show everywhere',
              })) && save.mutate('all')
            }
          />
          Their reports’ work in every project
        </label>
      </fieldset>
      <ErrorText error={settings.error ?? save.error} />
    </Section>
  );
}

function ScimTokens() {
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [created, setCreated] = useState<{ token: string; base_url: string } | null>(null);
  const tokens = useQuery({
    queryKey: ['scim-tokens'],
    queryFn: () => unwrap(api.GET('/api/v1/admin/scim-tokens')),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['scim-tokens'] });
  const create = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/admin/scim-tokens', { body: { name: name || 'SCIM' } })),
    onSuccess: async (t) => {
      setCreated({ token: t.token, base_url: t.base_url });
      setName('');
      await refresh();
    },
  });
  const revoke = useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE('/api/v1/admin/scim-tokens/{token_id}', { params: { path: { token_id: id } } })),
    onSuccess: refresh,
  });
  const active = (tokens.data ?? []).filter((t) => !t.revoked_at);
  return (
    <Section
      title="SCIM provisioning"
      intro="Your identity provider creates, updates and deactivates people automatically, and keeps groups in sync as workspaces. Configure it with the base URL and a token below."
    >
      <p className="text-sm">
        Base URL: <Copyable value={`${window.location.origin}/scim/v2`} />
      </p>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <Field label="Token name" id="scim-name">
          <Input
            id="scim-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Entra ID"
          />
        </Field>
        <Button type="submit" disabled={create.isPending}>
          Create token
        </Button>
      </form>
      {created && <SecretOnce label="SCIM token" value={created.token} />}
      <ErrorText error={tokens.error ?? create.error ?? revoke.error} />
      {active.length > 0 && (
        <table className={table}>
          <thead>
            <tr>
              <th className={th}>Name</th>
              <th className={th}>Prefix</th>
              <th className={th}>Last used</th>
              <th className={th}>
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {active.map((t) => (
              <tr key={t.id}>
                <td className={td}>{t.name}</td>
                <td className={`${td} font-mono`}>{t.prefix}…</td>
                <td className={td}>{dateTime(t.last_used_at)}</td>
                <td className={td}>
                  <GhostButton
                    aria-label={`Revoke ${t.name}`}
                    onClick={async () =>
                      (await confirm({
                        title: `Revoke the SCIM token "${t.name}"?`,
                        body: 'Provisioning with it stops now.',
                        confirmLabel: 'Revoke',
                        danger: true,
                      })) && revoke.mutate(t.id)
                    }
                  >
                    Revoke
                  </GhostButton>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Section>
  );
}
