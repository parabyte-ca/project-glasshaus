import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import { api, unwrap, type Priority, type ScheduleSpec, type User } from '../api/client';
import { triggerLabel } from '../lib/automation';
import { ScheduleFields } from './AutomationRules';
import { Button, ErrorText, Field, GhostButton, Input, Select } from './ui';
import { useConfirm } from '../lib/confirm';

const PRIORITIES: Priority[] = ['none', 'low', 'medium', 'high', 'urgent'];

const defaultSchedule = (): ScheduleSpec => ({
  frequency: 'weekly',
  weekday: 0,
  hour: 9,
  minute: 0,
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
});

export function RecurringTasks({ projectId, users }: { projectId: string; users: User[] }) {
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const key = ['recurring', projectId];
  const items = useQuery({
    queryKey: key,
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/projects/{project_id}/recurring-tasks', {
          params: { path: { project_id: projectId } },
        }),
      ),
  });
  const [title, setTitle] = useState('');
  const [priority, setPriority] = useState<Priority>('none');
  const [assignee, setAssignee] = useState('');
  const [dueIn, setDueIn] = useState('');
  const [schedule, setSchedule] = useState<ScheduleSpec>(defaultSchedule);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: key });

  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/projects/{project_id}/recurring-tasks', {
          params: { path: { project_id: projectId } },
          body: {
            template: {
              title,
              priority,
              assignee_id: assignee || null,
              due_in_days: dueIn === '' ? null : Number(dueIn),
            },
            schedule,
          },
        }),
      ),
    onSuccess: () => {
      setTitle('');
      setDueIn('');
      refresh();
    },
  });
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      unwrap(
        api.PATCH('/api/v1/recurring-tasks/{recurring_id}', {
          params: { path: { recurring_id: id } },
          body: { enabled },
        }),
      ),
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE('/api/v1/recurring-tasks/{recurring_id}', { params: { path: { recurring_id: id } } }),
      ),
    onSettled: refresh,
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };

  return (
    <div className="flex flex-col gap-4">
      <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
        {items.data?.length === 0 && (
          <li className="p-3 text-sm text-slate-600 dark:text-slate-400">No recurring tasks yet.</li>
        )}
        {items.data?.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 p-3 text-sm">
            <span>
              <span
                className={`font-medium ${r.enabled ? '' : 'text-slate-500 dark:text-slate-400 line-through'}`}
              >
                {r.template.title}
              </span>{' '}
              <span className="text-slate-600 dark:text-slate-400">
                {triggerLabel({ type: 'scheduled', schedule: r.schedule })} · next{' '}
                {new Date(r.next_run_at).toLocaleString()}
              </span>
            </span>
            <span className="flex gap-2">
              <GhostButton
                aria-label={`${r.enabled ? 'Pause' : 'Resume'} ${r.template.title}`}
                onClick={() => toggle.mutate({ id: r.id, enabled: !r.enabled })}
              >
                {r.enabled ? 'Pause' : 'Resume'}
              </GhostButton>
              <GhostButton
                aria-label={`Delete recurring ${r.template.title}`}
                onClick={async () =>
                  (await confirm({
                    title: `Stop creating "${r.template.title}"?`,
                    body: 'Tasks it already created stay.',
                    confirmLabel: 'Stop',
                    danger: true,
                  })) && remove.mutate(r.id)
                }
              >
                Delete
              </GhostButton>
            </span>
          </li>
        ))}
      </ul>
      <form
        aria-label="New recurring task"
        onSubmit={onSubmit}
        className="flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 p-4 dark:border-slate-800"
      >
        <Field label="Task title" id="rec-title">
          <Input
            id="rec-title"
            required
            maxLength={500}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </Field>
        <Field label="Priority" id="rec-priority">
          <Select
            id="rec-priority"
            value={priority}
            onChange={(e) => setPriority(e.target.value as Priority)}
          >
            {PRIORITIES.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </Select>
        </Field>
        <Field label="Assignee" id="rec-assignee">
          <Select id="rec-assignee" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
            <option value="">Unassigned</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Due after (days)" id="rec-due">
          <Input
            id="rec-due"
            type="number"
            min={0}
            max={365}
            className="w-24"
            value={dueIn}
            onChange={(e) => setDueIn(e.target.value)}
          />
        </Field>
        <ScheduleFields
          idPrefix="rec"
          value={schedule}
          onChange={(patch) => setSchedule((s) => ({ ...s, ...patch }))}
        />
        <Button type="submit" disabled={create.isPending}>
          Add recurring task
        </Button>
      </form>
      <ErrorText error={create.error ?? toggle.error ?? remove.error} />
    </div>
  );
}

export function SaveAsTemplate({ projectId, projectName }: { projectId: string; projectName: string }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(projectName);
  const [description, setDescription] = useState('');
  const [includeTasks, setIncludeTasks] = useState(true);
  const [includeAutomations, setIncludeAutomations] = useState(true);
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/project-templates', {
          body: {
            project_id: projectId,
            name,
            description,
            include_tasks: includeTasks,
            include_automations: includeAutomations,
          },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['project-templates'] }),
  });
  return (
    <form
      aria-label="Save as template"
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <p className="text-sm text-slate-600 dark:text-slate-400">
        Saves statuses, custom fields, shared views and, optionally, tasks (with relative dates),
        dependencies, automation rules and recurring tasks. People and comments are not copied.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Template name" id="tpl-name">
          <Input
            id="tpl-name"
            required
            maxLength={100}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <Field label="Description" id="tpl-desc">
          <Input
            id="tpl-desc"
            maxLength={2000}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={includeTasks} onChange={(e) => setIncludeTasks(e.target.checked)} />
        Include tasks and dependencies
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={includeAutomations}
          onChange={(e) => setIncludeAutomations(e.target.checked)}
        />
        Include automation rules and recurring tasks
      </label>
      <div>
        <Button type="submit" disabled={save.isPending}>
          Save template
        </Button>
      </div>
      {save.data && (
        <p role="status" className="text-sm text-emerald-700 dark:text-emerald-400">
          Saved “{save.data.name}”: {save.data.summary.tasks} tasks, {save.data.summary.rules} rules. Use it
          from New project on the home page.
        </p>
      )}
      <ErrorText error={save.error} />
    </form>
  );
}
