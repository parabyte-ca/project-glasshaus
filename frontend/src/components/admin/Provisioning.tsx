import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api, unwrap } from '../../api/client';
import { Button, ErrorText, Field, GhostButton, Input } from '../ui';
import { Copyable, SecretOnce, Section } from './common';
import { dateTime, table, td, th } from './format';
import { useConfirm } from '../../lib/confirm';

export function Provisioning() {
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
