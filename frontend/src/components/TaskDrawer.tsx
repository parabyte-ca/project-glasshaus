import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import { api, unwrap, type CustomField, type ProjectDetail, type User } from '../api/client';
import { PRIORITIES } from '../lib/grouping';
import { CommentComposer } from './CommentComposer';
import { DependencyEditor } from './DependencyEditor';
import { FieldEditor } from './FieldEditor';
import { Markdown } from './Markdown';
import { ErrorText, GhostButton, Input, Select } from './ui';

interface Props {
  taskRef: string;
  project: ProjectDetail;
  fields: CustomField[];
  users: User[];
  onClose: () => void;
}

function describe(type: string, data: Record<string, unknown>): string {
  if (type === 'task.updated') {
    const changes = Object.keys((data.changes as Record<string, unknown>) ?? {});
    return `changed ${changes.join(', ').replace(/_id\b/g, '').replace(/_/g, ' ')}`;
  }
  return type.replace('.', ' ').replace(/^(\w+) (\w+)$/, '$2 $1');
}

export function TaskDrawer({ taskRef, project, fields, users, onClose }: Props) {
  const queryClient = useQueryClient();
  const panel = useRef<HTMLDivElement>(null);
  const [editingDescription, setEditingDescription] = useState(false);
  const names = new Map(users.map((u) => [u.id, u.name]));

  const task = useQuery({
    queryKey: ['task', taskRef],
    queryFn: () => unwrap(api.GET('/api/v1/tasks/{ref}', { params: { path: { ref: taskRef } } })),
  });
  const id = task.data?.id;
  const comments = useQuery({
    queryKey: ['comments', id],
    enabled: !!id,
    queryFn: () => unwrap(api.GET('/api/v1/tasks/{ref}/comments', { params: { path: { ref: id! } } })),
  });
  const activity = useQuery({
    queryKey: ['activity', 'task', id],
    enabled: !!id,
    queryFn: () => unwrap(api.GET('/api/v1/activity', { params: { query: { task: id!, limit: 30 } } })),
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['task'] });
    void queryClient.invalidateQueries({ queryKey: ['tasks', project.id] });
    void queryClient.invalidateQueries({ queryKey: ['activity'] });
  };
  const update = useMutation({
    mutationFn: (patch: Record<string, unknown>) =>
      unwrap(
        api.PATCH('/api/v1/tasks/{ref}', {
          params: { path: { ref: id! } },
          body: { ...patch, expected_version: task.data!.version },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(['task', taskRef], data),
    onSettled: refresh,
  });
  const comment = useMutation({
    mutationFn: (body: string) =>
      unwrap(api.POST('/api/v1/tasks/{ref}/comments', { params: { path: { ref: id! } }, body: { body } })),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['comments', id] });
      void queryClient.invalidateQueries({ queryKey: ['activity'] });
    },
  });

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      previous?.focus();
    };
  }, [onClose]);

  const t = task.data;
  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div role="presentation" className="absolute inset-0 bg-slate-900/40" onClick={onClose} />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="task-title"
        tabIndex={-1}
        className="relative flex h-full w-full max-w-2xl flex-col gap-4 overflow-y-auto bg-white p-5 shadow-xl outline-none dark:bg-slate-950"
      >
        <div className="flex items-start justify-between gap-2">
          <span className="font-mono text-xs text-slate-600 dark:text-slate-400">{t?.key ?? taskRef}</span>
          <GhostButton onClick={onClose} aria-label="Close task">
            Close
          </GhostButton>
        </div>
        {task.isError && <ErrorText error={task.error} />}
        {t && (
          <>
            <label htmlFor="task-title" className="sr-only">
              Title
            </label>
            <input
              id="task-title"
              key={`title-${t.version}`}
              defaultValue={t.title}
              maxLength={500}
              onBlur={(e) =>
                e.target.value.trim() &&
                e.target.value !== t.title &&
                update.mutate({ title: e.target.value })
              }
              className="rounded border border-transparent px-1 text-xl font-semibold hover:border-slate-300 focus:border-sky-600 dark:bg-slate-950"
            />
            <ErrorText error={update.error} />

            <dl className="grid grid-cols-[8rem_1fr] items-center gap-x-3 gap-y-2 text-sm">
              <dt>
                <label htmlFor="d-status">Status</label>
              </dt>
              <dd>
                <Select
                  id="d-status"
                  value={t.status.id}
                  onChange={(e) => update.mutate({ status_id: e.target.value })}
                >
                  {project.statuses.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </Select>
              </dd>
              <dt>
                <label htmlFor="d-priority">Priority</label>
              </dt>
              <dd>
                <Select
                  id="d-priority"
                  value={t.priority}
                  onChange={(e) => update.mutate({ priority: e.target.value })}
                >
                  {PRIORITIES.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </Select>
              </dd>
              <dt>
                <label htmlFor="d-assignee">Assignee</label>
              </dt>
              <dd>
                <Select
                  id="d-assignee"
                  value={t.assignee_id ?? ''}
                  onChange={(e) => update.mutate({ assignee_id: e.target.value || null })}
                >
                  <option value="">Unassigned</option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name}
                    </option>
                  ))}
                </Select>
              </dd>
              <dt>
                <label htmlFor="d-start">Start</label>
              </dt>
              <dd>
                <Input
                  id="d-start"
                  type="date"
                  value={t.start_date ?? ''}
                  onChange={(e) => update.mutate({ start_date: e.target.value || null })}
                />
              </dd>
              <dt>
                <label htmlFor="d-due">Due</label>
              </dt>
              <dd>
                <Input
                  id="d-due"
                  type="date"
                  value={t.due_date ?? ''}
                  onChange={(e) => update.mutate({ due_date: e.target.value || null })}
                />
              </dd>
              {fields.map((f) => (
                <div key={`${f.id}-${t.version}`} className="contents">
                  <dt>
                    <label htmlFor={`cf-${f.id}`}>{f.name}</label>
                  </dt>
                  <dd>
                    <FieldEditor
                      field={f}
                      value={t.custom_fields[f.id]}
                      users={users}
                      onChange={(value) => update.mutate({ custom_fields: { [f.id]: value } })}
                    />
                  </dd>
                </div>
              ))}
            </dl>

            <DependencyEditor
              task={t}
              canEdit={project.my_role === 'admin' || project.my_role === 'editor'}
            />

            <section aria-labelledby="desc-h" className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <h3 id="desc-h" className="text-sm font-semibold">
                  Description
                </h3>
                <GhostButton onClick={() => setEditingDescription((v) => !v)}>
                  {editingDescription ? 'Preview' : 'Edit'}
                </GhostButton>
              </div>
              {editingDescription ? (
                <>
                  <label htmlFor="d-description" className="sr-only">
                    Description (markdown)
                  </label>
                  <textarea
                    id="d-description"
                    rows={8}
                    defaultValue={t.description}
                    onBlur={(e) =>
                      e.target.value !== t.description && update.mutate({ description: e.target.value })
                    }
                    className="rounded-md border border-slate-300 bg-white p-2 font-mono text-sm dark:border-slate-600 dark:bg-slate-900"
                  />
                </>
              ) : t.description ? (
                <Markdown text={t.description} />
              ) : (
                <p className="text-sm text-slate-500">No description.</p>
              )}
            </section>

            <section aria-labelledby="comments-h" className="flex flex-col gap-3">
              <h3 id="comments-h" className="text-sm font-semibold">
                Comments
              </h3>
              <ul className="flex flex-col gap-3">
                {comments.data?.map((c) => (
                  <li key={c.id} className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
                    <p className="mb-1 text-xs text-slate-600 dark:text-slate-400">
                      {(c.author_id && names.get(c.author_id)) ?? 'Someone'} ·{' '}
                      {new Date(c.created_at).toLocaleString()}
                      {c.edited_at && ' (edited)'}
                    </p>
                    <Markdown text={c.body} />
                  </li>
                ))}
              </ul>
              <CommentComposer
                users={users}
                busy={comment.isPending}
                onSubmit={(body) => comment.mutate(body)}
              />
              <ErrorText error={comment.error} />
            </section>

            <section aria-labelledby="activity-h">
              <h3 id="activity-h" className="mb-2 text-sm font-semibold">
                Activity
              </h3>
              <ol className="flex flex-col gap-1 text-xs text-slate-600 dark:text-slate-400">
                {activity.data?.items.map((a) => (
                  <li key={a.id}>
                    <span className="font-medium text-slate-800 dark:text-slate-200">
                      {(a.actor.user_id && names.get(a.actor.user_id)) ?? a.actor.method}
                    </span>{' '}
                    {describe(a.type, a.data)} · {new Date(a.occurred_at).toLocaleString()}
                  </li>
                ))}
              </ol>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
