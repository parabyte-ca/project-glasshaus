import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { useParams } from 'react-router';

import { api, unwrap, type Task } from '../api/client';
import { Button, ErrorText, Input, Select } from '../components/ui';

const PRIORITIES = ['none', 'low', 'medium', 'high', 'urgent'] as const;

export function ProjectPage() {
  const { projectKey = '' } = useParams();
  const queryClient = useQueryClient();
  const [title, setTitle] = useState('');
  const [showDone, setShowDone] = useState(false);

  const project = useQuery({
    queryKey: ['project', projectKey],
    queryFn: () =>
      unwrap(api.GET('/api/v1/projects/by-key/{key}', { params: { path: { key: projectKey } } })),
  });
  const projectId = project.data?.id;
  const categories = showDone
    ? undefined
    : (['backlog', 'todo', 'in_progress'] as ('backlog' | 'todo' | 'in_progress')[]);
  const tasks = useQuery({
    queryKey: ['tasks', projectId, showDone],
    enabled: !!projectId,
    placeholderData: keepPreviousData,
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/tasks', {
          params: {
            query: {
              project_id: projectId,
              status_categories: categories,
              limit: 200,
              top_level_only: false,
            },
          },
        }),
      ),
  });
  const users = useQuery({ queryKey: ['users'], queryFn: () => unwrap(api.GET('/api/v1/users')) });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['tasks', projectId] });
  const create = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/tasks', { body: { project_id: projectId!, title } })),
    onSuccess: () => {
      setTitle('');
      void invalidate();
    },
  });
  const update = useMutation({
    mutationFn: ({ task, patch }: { task: Task; patch: Record<string, unknown> }) =>
      unwrap(
        api.PATCH('/api/v1/tasks/{ref}', {
          params: { path: { ref: task.id } },
          body: { ...patch, expected_version: task.version },
        }),
      ),
    onSettled: () => void invalidate(),
  });

  const onCreate = (e: FormEvent) => {
    e.preventDefault();
    if (title.trim()) create.mutate();
  };

  if (project.isError) return <ErrorText error={project.error} />;
  if (!project.data) return <p role="status">Loading…</p>;

  const names = new Map(users.data?.map((u) => [u.id, u.name]));
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-bold">
          {project.data.name}{' '}
          <span className="font-mono text-sm text-slate-600 dark:text-slate-400">{project.data.key}</span>
        </h1>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} />
          Show completed
        </label>
      </div>

      <form onSubmit={onCreate} className="flex gap-2">
        <label htmlFor="new-task" className="sr-only">
          New task title
        </label>
        <Input
          id="new-task"
          placeholder="Add a task and press Enter"
          className="flex-1"
          value={title}
          maxLength={500}
          onChange={(e) => setTitle(e.target.value)}
        />
        <Button type="submit" disabled={create.isPending || !title.trim()}>
          Add
        </Button>
      </form>
      <ErrorText error={create.error ?? update.error} />

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Tasks in {project.data.name}</caption>
          <thead className="border-b border-slate-200 text-xs text-slate-600 uppercase dark:border-slate-800 dark:text-slate-400">
            <tr>
              <th scope="col" className="py-2 pr-3">
                Key
              </th>
              <th scope="col" className="py-2 pr-3">
                Title
              </th>
              <th scope="col" className="py-2 pr-3">
                Status
              </th>
              <th scope="col" className="py-2 pr-3">
                Priority
              </th>
              <th scope="col" className="py-2 pr-3">
                Assignee
              </th>
              <th scope="col" className="py-2 pr-3">
                Due
              </th>
            </tr>
          </thead>
          <tbody>
            {tasks.data?.items.map((task) => (
              <tr key={task.id} className="border-b border-slate-100 dark:border-slate-900">
                <td className="py-2 pr-3 font-mono text-xs whitespace-nowrap">{task.key}</td>
                <td className="py-2 pr-3">{task.title}</td>
                <td className="py-2 pr-3">
                  <Select
                    aria-label={`Status of ${task.key}`}
                    value={task.status.id}
                    onChange={(e) => update.mutate({ task, patch: { status_id: e.target.value } })}
                  >
                    {project.data.statuses.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </Select>
                </td>
                <td className="py-2 pr-3">
                  <Select
                    aria-label={`Priority of ${task.key}`}
                    value={task.priority}
                    onChange={(e) => update.mutate({ task, patch: { priority: e.target.value } })}
                  >
                    {PRIORITIES.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </Select>
                </td>
                <td className="py-2 pr-3 whitespace-nowrap">
                  {task.assignee_id ? names.get(task.assignee_id) : '—'}
                </td>
                <td className="py-2 pr-3 whitespace-nowrap">{task.due_date ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {tasks.data?.items.length === 0 && (
          <p className="py-6 text-center text-slate-600 dark:text-slate-400">No open tasks.</p>
        )}
      </div>
    </div>
  );
}
