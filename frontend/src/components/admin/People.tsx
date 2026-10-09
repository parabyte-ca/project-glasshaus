import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import { api, fieldError, type Schemas, unwrap, type User } from '../../api/client';
import { useAuth } from '../../auth/useAuth';
import { Button, ErrorText, Field, GhostButton, Input, ScrollArea, Select } from '../ui';
import { Section } from './common';
import { dateTime, table, td, th } from './format';
import { useConfirm } from '../../lib/confirm';

type Role = Schemas['OrgRole'];
const ROLES: Role[] = ['owner', 'admin', 'member', 'guest'];
const ROLE_HELP: Record<Role, string> = {
  owner: 'Owners have full control, including over other owners and admins.',
  admin: 'Admins manage people, sign-in, integrations and organization settings.',
  member: 'Members work in the projects they belong to.',
  guest: 'Guests see only the projects they are added to, with no organization-wide access.',
};

function ResetPassword({ user, onDone }: { user: User; onDone: () => void }) {
  const [password, setPassword] = useState('');
  const reset = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/admin/users/{user_id}/password', {
          params: { path: { user_id: user.id } },
          body: { new_password: password },
        }),
      ),
    onSuccess: onDone,
  });
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        reset.mutate();
      }}
    >
      <Field label={`New password for ${user.name}`} id={`pw-${user.id}`}>
        <Input
          id={`pw-${user.id}`}
          type="password"
          autoComplete="new-password"
          minLength={12}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </Field>
      <Button type="submit" disabled={password.length < 12 || reset.isPending}>
        Set password
      </Button>
      <GhostButton onClick={onDone}>Cancel</GhostButton>
      <ErrorText error={reset.error} />
    </form>
  );
}

export function People() {
  const confirm = useConfirm();
  const { user: me } = useAuth();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState('');
  const [resetFor, setResetFor] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [draft, setDraft] = useState({ email: '', name: '', org_role: 'member' as Role, password: '' });
  const users = useQuery({
    queryKey: ['users', 'admin', query],
    queryFn: () =>
      unwrap(api.GET('/api/v1/users', { params: { query: { q: query || undefined, limit: 500 } } })),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['users'] });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas['UserUpdate'] }) =>
      unwrap(api.PATCH('/api/v1/users/{user_id}', { params: { path: { user_id: id } }, body })),
    onSuccess: refresh,
  });
  const signOut = useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.POST('/api/v1/admin/users/{user_id}/sessions/revoke', { params: { path: { user_id: id } } }),
      ),
    onSuccess: () =>
      setNotice('Signed out everywhere: sessions, API tokens and connected apps were revoked.'),
  });
  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/users', {
          body: {
            email: draft.email,
            name: draft.name,
            org_role: draft.org_role,
            password: draft.password || null,
          },
        }),
      ),
    onSuccess: async () => {
      setDraft({ email: '', name: '', org_role: 'member', password: '' });
      await refresh();
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };

  return (
    <div className="flex flex-col gap-8">
      <Section
        title="People"
        intro="Deactivated people cannot sign in and their sessions end immediately; their work and history stay. Owners can only be changed by owners."
      >
        <Field label="Search people" id="people-search">
          <Input
            id="people-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="max-w-xs"
          />
        </Field>
        {notice && (
          <p role="status" className="text-sm text-emerald-700 dark:text-emerald-400">
            {notice}
          </p>
        )}
        <ErrorText error={users.error ?? update.error ?? signOut.error} />
        <ScrollArea label="People">
          <table className={table}>
            <thead>
              <tr>
                <th className={th}>Name</th>
                <th className={th}>Email</th>
                <th className={th}>Role</th>
                <th className={th}>Last sign-in</th>
                <th className={th}>Status</th>
                <th className={th}>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {(users.data ?? []).map((u) => (
                <tr key={u.id} className={u.is_active ? '' : 'text-slate-500 dark:text-slate-400'}>
                  <td className={td}>{u.name}</td>
                  <td className={td}>{u.email}</td>
                  <td className={td}>
                    <Select
                      aria-label={`Role for ${u.name}`}
                      value={u.org_role}
                      disabled={u.id === me.id || (u.org_role === 'owner' && me.org_role !== 'owner')}
                      onChange={async (e) => {
                        const role = e.target.value as Role;
                        const ok = await confirm({
                          title: `Make ${u.name} ${role === 'admin' || role === 'owner' ? 'an' : 'a'} ${role}?`,
                          body: ROLE_HELP[role],
                          confirmLabel: 'Change role',
                        });
                        if (ok) update.mutate({ id: u.id, body: { org_role: role } });
                      }}
                    >
                      {ROLES.filter(
                        (r) => r !== 'owner' || me.org_role === 'owner' || u.org_role === 'owner',
                      ).map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </Select>
                  </td>
                  <td className={td}>{dateTime(u.last_login_at)}</td>
                  <td className={td}>{u.is_active ? 'Active' : 'Deactivated'}</td>
                  <td className={`${td} whitespace-nowrap`}>
                    {u.id !== me.id && (
                      <div className="flex flex-wrap gap-1">
                        <GhostButton
                          aria-label={`${u.is_active ? 'Deactivate' : 'Reactivate'} ${u.name}`}
                          onClick={async () => {
                            if (
                              !u.is_active ||
                              (await confirm({
                                title: `Deactivate ${u.name}?`,
                                body: 'They are signed out everywhere now and cannot sign in until reactivated.',
                                confirmLabel: 'Deactivate',
                                danger: true,
                              }))
                            )
                              update.mutate({ id: u.id, body: { is_active: !u.is_active } });
                          }}
                        >
                          {u.is_active ? 'Deactivate' : 'Reactivate'}
                        </GhostButton>
                        <GhostButton
                          aria-label={`Reset password for ${u.name}`}
                          onClick={() => setResetFor(u.id)}
                        >
                          Reset password
                        </GhostButton>
                        <GhostButton
                          aria-label={`Sign out ${u.name} everywhere`}
                          onClick={() => signOut.mutate(u.id)}
                        >
                          Sign out everywhere
                        </GhostButton>
                      </div>
                    )}
                    {resetFor === u.id && (
                      <div className="mt-2">
                        <ResetPassword
                          user={u}
                          onDone={() => {
                            setResetFor(null);
                            setNotice(`Password set for ${u.name}; their sessions were ended.`);
                          }}
                        />
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollArea>
      </Section>

      <Section
        title="Add a person"
        intro="Leave the password empty when they will sign in with single sign-on, or set a temporary one and share it securely."
      >
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <Field label="Email" id="new-email" error={fieldError(create.error, 'email')}>
            <Input
              id="new-email"
              type="email"
              required
              value={draft.email}
              onChange={(e) => setDraft({ ...draft, email: e.target.value })}
            />
          </Field>
          <Field label="Name" id="new-name" error={fieldError(create.error, 'name')}>
            <Input
              id="new-name"
              required
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </Field>
          <Field label="Role" id="new-role">
            <Select
              id="new-role"
              value={draft.org_role}
              onChange={(e) => setDraft({ ...draft, org_role: e.target.value as Role })}
            >
              {ROLES.filter((r) => r !== 'owner' || me.org_role === 'owner').map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Temporary password (optional)"
            id="new-password"
            error={fieldError(create.error, 'password')}
          >
            <Input
              id="new-password"
              type="password"
              autoComplete="new-password"
              value={draft.password}
              onChange={(e) => setDraft({ ...draft, password: e.target.value })}
            />
          </Field>
          <Button type="submit" disabled={create.isPending || !draft.email || !draft.name}>
            Add person
          </Button>
        </form>
        <ErrorText error={create.error} />
      </Section>
    </div>
  );
}
