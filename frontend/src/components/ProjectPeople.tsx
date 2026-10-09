import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useId, useState, type FormEvent } from 'react';

import { api, unwrap, type ProjectDetail, type User } from '../api/client';
import { ONBOARDING_KEY } from '../lib/onboarding';
import { Button, ErrorText, GhostButton, Select } from './ui';
import { useConfirm } from '../lib/confirm';

type Role = 'admin' | 'editor' | 'commenter' | 'viewer';
const ROLES: [Role, string][] = [
  ['editor', 'Editor'],
  ['commenter', 'Commenter'],
  ['viewer', 'Viewer'],
  ['admin', 'Admin'],
];

const initials = (name: string) =>
  name
    .split(/\s+/)
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();

/** Who works on this project; project admins add and remove people here. */
export function ProjectPeople({
  project,
  users,
  defaultOpen = false,
}: {
  project: ProjectDetail;
  users: User[];
  defaultOpen?: boolean;
}) {
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(defaultOpen);
  const [person, setPerson] = useState('');
  const [role, setRole] = useState<Role>('editor');
  const panelId = useId();
  const key = ['members', project.id];
  const members = useQuery({
    queryKey: key,
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/projects/{project_id}/members', { params: { path: { project_id: project.id } } }),
      ),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: key });
    void queryClient.invalidateQueries({ queryKey: ONBOARDING_KEY });
  };
  const add = useMutation({
    mutationFn: () =>
      unwrap(
        api.PUT('/api/v1/projects/{project_id}/members', {
          params: { path: { project_id: project.id } },
          body: { user_id: person, role },
        }),
      ),
    onSuccess: () => {
      setPerson('');
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (userId: string) =>
      unwrap(
        api.DELETE('/api/v1/projects/{project_id}/members/{user_id}', {
          params: { path: { project_id: project.id, user_id: userId } },
        }),
      ),
    onSettled: refresh,
  });

  const names = new Map(users.map((u) => [u.id, u.name]));
  const list = members.data ?? [];
  const memberIds = new Set(list.map((m) => m.user_id));
  const candidates = users.filter((u) => u.is_active && !memberIds.has(u.id));
  const canManage = project.my_role === 'admin';
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (person) add.mutate();
  };

  return (
    <div className="relative" data-tour="collaborators">
      <GhostButton aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((v) => !v)}>
        <span className="mr-2 inline-flex -space-x-1.5" aria-hidden="true">
          {list.slice(0, 3).map((m) => (
            <span
              key={m.user_id}
              className="flex h-5 w-5 items-center justify-center rounded-full bg-sky-100 text-[10px] font-semibold text-sky-900 ring-2 ring-white dark:bg-sky-900 dark:text-sky-100 dark:ring-slate-950"
            >
              {initials(names.get(m.user_id) ?? '?')}
            </span>
          ))}
        </span>
        People ({list.length})
      </GhostButton>
      {open && (
        <section
          id={panelId}
          aria-label="Project people"
          className="absolute right-0 z-20 mt-2 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4 text-sm shadow-lg dark:border-slate-700 dark:bg-slate-900"
        >
          <ul className="flex flex-col gap-1.5">
            {list.length === 0 && (
              <li className="text-slate-600 dark:text-slate-400">
                No one has been added yet; workspace members can still see this project.
              </li>
            )}
            {list.map((m) => (
              <li key={m.user_id} className="flex items-center justify-between gap-2">
                <span>
                  {names.get(m.user_id) ?? 'Unknown person'}{' '}
                  <span className="text-xs text-slate-600 dark:text-slate-400">{m.role}</span>
                </span>
                {canManage && (
                  <button
                    type="button"
                    aria-label={`Remove ${names.get(m.user_id) ?? 'person'} from the project`}
                    onClick={async () =>
                      (await confirm({
                        title: `Remove ${names.get(m.user_id) ?? 'this person'} from ${project.name}?`,
                        body: 'They lose access to the project unless the whole organization has it.',
                        confirmLabel: 'Remove',
                        danger: true,
                      })) && remove.mutate(m.user_id)
                    }
                    className="min-h-6 rounded px-1.5 text-xs hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-sky-600 dark:hover:bg-slate-800"
                  >
                    Remove
                  </button>
                )}
              </li>
            ))}
          </ul>
          {canManage && (
            <form
              onSubmit={submit}
              className="flex flex-wrap items-end gap-2 border-t border-slate-200 pt-3 dark:border-slate-700"
            >
              <Select
                aria-label="Person to add"
                value={person}
                onChange={(e) => setPerson(e.target.value)}
                className="min-w-0 flex-1"
              >
                <option value="">Add a person…</option>
                {candidates.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name}
                  </option>
                ))}
              </Select>
              <Select aria-label="Role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
                {ROLES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
              <Button type="submit" disabled={!person || add.isPending}>
                Add
              </Button>
            </form>
          )}
          <ErrorText error={members.error ?? add.error ?? remove.error} />
        </section>
      )}
    </div>
  );
}
