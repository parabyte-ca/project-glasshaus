import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useId, useState } from 'react';
import { Link } from 'react-router';

import { api, unwrap, type Schemas, type User } from '../api/client';
import { rescueFocus } from '../lib/focus';
import { PRIORITY_LABEL } from '../lib/labels';
import { toast } from '../lib/toast';
import { Button, ErrorText, Field, GhostButton, Input, linkClass, Select } from './ui';

type Suggestion = Schemas['SuggestionRead'];
type Decision = Schemas['SuggestionDecision'];
type NewTask = Schemas['NewTask-Output'];

const KIND: Record<Suggestion['kind'], string> = {
  comment: 'Follow-up comment',
  due_date: 'New due date',
  assign: 'New owner',
  task: 'New task',
};
const SOURCE: Record<Suggestion['source'], string> = { rules: 'Rule', ai: 'AI', notes: 'From notes' };
const STATUS: Record<Suggestion['status'], string> = {
  open: 'Waiting',
  approved: 'Approved',
  dismissed: 'Dismissed',
  stale: 'Set aside (task changed)',
  expired: 'Expired',
  undone: 'Undone',
};
const MENTION = /^@\[([^\]]+)\]\(user:[0-9a-fA-F-]{36}\)\s*/;

const shortDate = (iso: string | null | undefined) =>
  iso
    ? new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      })
    : 'none';

/** Split "@[Name](user:id) text" into the person it addresses and the editable text. */
/** After a change to a task: its list, its drawer and its comments may be stale. */
async function refreshTask(queryClient: QueryClient, taskId: string | undefined): Promise<void> {
  await queryClient.invalidateQueries({ queryKey: ['tasks'] });
  if (taskId) {
    await queryClient.invalidateQueries({ queryKey: ['task', taskId] });
    await queryClient.invalidateQueries({ queryKey: ['comments', taskId] });
  }
}

function splitMention(comment: string): { prefix: string; name: string | null; text: string } {
  const m = MENTION.exec(comment);
  return m
    ? { prefix: m[0], name: m[1] ?? null, text: comment.slice(m[0].length) }
    : { prefix: '', name: null, text: comment };
}

function SuggestionCard({
  s,
  projectId,
  projectKey,
  canApprove,
  users,
}: {
  s: Suggestion;
  projectId: string;
  projectKey: string;
  canApprove: boolean;
  users: User[];
}) {
  const id = useId();
  const queryClient = useQueryClient();
  const mention = splitMention(s.comment ?? '');
  const [text, setText] = useState(mention.text);
  const [due, setDue] = useState(s.due_date ?? '');
  const [owner, setOwner] = useState(s.assignee_id ?? '');
  const [task, setTask] = useState<NewTask | null>(s.new_task ?? null);
  const path = { params: { path: { project_id: projectId, suggestion_id: s.id } } };
  const done = async () => {
    await queryClient.invalidateQueries({ queryKey: ['suggestions', projectId] });
    await refreshTask(queryClient, s.task?.id);
  };
  const decision = (): Decision => {
    if (s.kind === 'comment' && text !== mention.text) return { comment: `${mention.prefix}${text}` };
    if (s.kind === 'due_date' && due && due !== s.due_date) return { due_date: due };
    if (s.kind === 'assign' && owner && owner !== s.assignee_id) return { assignee_id: owner };
    if (s.kind === 'task' && task) return { new_task: task };
    return {};
  };
  const approve = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/projects/{project_id}/assistant/suggestions/{suggestion_id}/approve', {
          ...path,
          body: decision(),
        }),
      ),
    onSuccess: async (r) => {
      toast(r.result ?? 'Done');
      await done();
    },
    onError: () => void done(),
  });
  const dismiss = useMutation({
    mutationFn: () =>
      unwrap(api.POST('/api/v1/projects/{project_id}/assistant/suggestions/{suggestion_id}/dismiss', path)),
    onSuccess: async () => {
      toast('Dismissed');
      await done();
    },
  });
  const busy = approve.isPending || dismiss.isPending;
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-slate-200 p-3 dark:border-slate-800">
      <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
        <h3 id={`${id}-h`} className="font-semibold">
          {KIND[s.kind]}
          {s.task && (
            <>
              {' · '}
              <Link className={`font-mono ${linkClass}`} to={`/projects/${projectKey}?task=${s.task.key}`}>
                {s.task.key}
              </Link>{' '}
              <span className="font-normal">{s.task.title}</span>
            </>
          )}
        </h3>
        <span className="rounded bg-slate-100 px-1.5 text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-300">
          {SOURCE[s.source]}
        </span>
      </div>
      <p className="text-sm text-slate-600 dark:text-slate-400">{s.reason}</p>
      {s.kind === 'comment' && (
        <Field label={mention.name ? `Comment to @${mention.name}` : 'Comment'} id={`${id}-c`}>
          <textarea
            id={`${id}-c`}
            rows={3}
            readOnly={!canApprove}
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="rounded-md border border-slate-300 bg-white p-2 text-sm dark:border-slate-700 dark:bg-slate-900"
          />
        </Field>
      )}
      {s.kind === 'due_date' && (
        <div className="flex flex-wrap items-end gap-3 text-sm">
          <span className="self-center">Now due {shortDate(s.task?.due_date)}</span>
          <Field label="New due date" id={`${id}-d`}>
            <Input
              id={`${id}-d`}
              type="date"
              value={due}
              disabled={!canApprove}
              onChange={(e) => setDue(e.target.value)}
            />
          </Field>
        </div>
      )}
      {s.kind === 'assign' && (
        <div className="flex flex-wrap items-end gap-3 text-sm">
          <span className="self-center">Now: {s.task?.assignee ?? 'nobody'}</span>
          <Field label="New owner" id={`${id}-o`}>
            <Select
              id={`${id}-o`}
              value={owner}
              disabled={!canApprove}
              onChange={(e) => setOwner(e.target.value)}
            >
              {!users.some((u) => u.id === owner) && (
                <option value={owner}>{s.assignee ?? 'Choose a person'}</option>
              )}
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      )}
      {s.kind === 'task' && task && (
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Title" id={`${id}-t`}>
            <Input
              id={`${id}-t`}
              className="w-72"
              value={task.title}
              readOnly={!canApprove}
              onChange={(e) => setTask({ ...task, title: e.target.value })}
            />
          </Field>
          <Field label="Priority" id={`${id}-p`}>
            <Select
              id={`${id}-p`}
              value={task.priority}
              disabled={!canApprove}
              onChange={(e) => setTask({ ...task, priority: e.target.value as NewTask['priority'] })}
            >
              {(['none', 'low', 'medium', 'high', 'urgent'] as const).map((p) => (
                <option key={p} value={p}>
                  {PRIORITY_LABEL[p]}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Due" id={`${id}-td`}>
            <Input
              id={`${id}-td`}
              type="date"
              value={task.due_date ?? ''}
              disabled={!canApprove}
              onChange={(e) => setTask({ ...task, due_date: e.target.value || null })}
            />
          </Field>
          <Field label="Owner" id={`${id}-to`}>
            <Select
              id={`${id}-to`}
              value={task.assignee_id ?? ''}
              disabled={!canApprove}
              onChange={(e) => setTask({ ...task, assignee_id: e.target.value || null })}
            >
              <option value="">Nobody</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
            </Select>
          </Field>
          {task.description && (
            <p className="w-full text-sm text-slate-600 dark:text-slate-400">{task.description}</p>
          )}
        </div>
      )}
      {canApprove && (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            disabled={
              busy || (s.kind === 'task' && !task?.title.trim()) || (s.kind === 'comment' && !text.trim())
            }
            onClick={(e) => {
              rescueFocus(e.currentTarget);
              approve.mutate();
            }}
            aria-describedby={`${id}-h`}
          >
            Approve
          </Button>
          <GhostButton
            type="button"
            disabled={busy}
            onClick={(e) => {
              rescueFocus(e.currentTarget);
              dismiss.mutate();
            }}
            aria-describedby={`${id}-h`}
          >
            Dismiss
          </GhostButton>
        </div>
      )}
      <ErrorText error={approve.error ?? dismiss.error} />
    </li>
  );
}

function Notes({ projectId }: { projectId: string }) {
  const id = useId();
  const queryClient = useQueryClient();
  const [text, setText] = useState('');
  const propose = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/projects/{project_id}/assistant/notes', {
          params: { path: { project_id: projectId } },
          body: { text },
        }),
      ),
    onSuccess: async (r) => {
      toast(`${r.length} task${r.length === 1 ? '' : 's'} proposed; approve the ones you want`);
      setText('');
      await queryClient.invalidateQueries({ queryKey: ['suggestions', projectId] });
    },
  });
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        propose.mutate();
      }}
    >
      <Field label="Turn meeting notes or an email into tasks" id={`${id}-n`}>
        <textarea
          id={`${id}-n`}
          rows={4}
          value={text}
          maxLength={20000}
          onChange={(e) => setText(e.target.value)}
          aria-describedby={`${id}-nh`}
          placeholder="Paste notes here."
          className="rounded-md border border-slate-300 bg-white p-2 text-sm dark:border-slate-700 dark:bg-slate-900"
        />
      </Field>
      <p id={`${id}-nh`} className="text-xs text-slate-600 dark:text-slate-400">
        Without AI, lines starting with “- [ ]”, “TODO:” or “Action:” become tasks.
      </p>
      <div>
        <GhostButton type="submit" disabled={propose.isPending || !text.trim()}>
          {propose.isPending ? 'Reading…' : 'Propose tasks'}
        </GhostButton>
      </div>
      <ErrorText error={propose.error} />
    </form>
  );
}

function UndoButton({ s, projectId }: { s: Suggestion; projectId: string }) {
  const queryClient = useQueryClient();
  const undo = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/projects/{project_id}/assistant/suggestions/{suggestion_id}/undo', {
          params: { path: { project_id: projectId, suggestion_id: s.id } },
        }),
      ),
    onSuccess: async () => {
      toast('Follow-up removed');
      await queryClient.invalidateQueries({ queryKey: ['suggestions', projectId] });
      await refreshTask(queryClient, s.task?.id);
    },
    onError: (err) => toast(err instanceof Error ? err.message : 'Could not undo', 'error'),
  });
  return (
    <GhostButton
      type="button"
      className="ml-2 px-2 py-0.5 text-xs"
      disabled={undo.isPending}
      aria-label={`Undo the follow-up on ${s.task?.key ?? 'this task'}`}
      onClick={() => undo.mutate()}
    >
      Undo
    </GhostButton>
  );
}

/** The assistant's approval queue: nothing changes until an editor or admin approves. */
export function AssistantSuggestions({
  projectId,
  projectKey,
  canApprove,
  users,
}: {
  projectId: string;
  projectKey: string;
  canApprove: boolean;
  users: User[];
}) {
  const id = useId();
  const [showDecided, setShowDecided] = useState(false);
  const path = { params: { path: { project_id: projectId } } };
  const open = useQuery({
    queryKey: ['suggestions', projectId, 'open'],
    queryFn: () => unwrap(api.GET('/api/v1/projects/{project_id}/assistant/suggestions', path)),
  });
  const decided = useQuery({
    queryKey: ['suggestions', projectId, 'decided'],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/projects/{project_id}/assistant/suggestions', {
          params: { path: { project_id: projectId }, query: { decided: true, limit: 30 } },
        }),
      ),
  });
  const list = open.data ?? [];
  const automatic = (decided.data ?? []).filter((s) => s.automatic && s.can_undo);
  return (
    <section aria-labelledby={`${id}-h`} className="flex flex-col gap-3">
      <h2 id={`${id}-h`} className="text-lg font-semibold">
        Suggestions {list.length > 0 && <span className="font-normal">({list.length})</span>}
      </h2>
      <p className="text-sm text-slate-600 dark:text-slate-400">
        {canApprove
          ? 'Nothing changes until you approve. Approved changes are made by the project assistant and say who approved them.'
          : 'Project editors and admins approve or dismiss these.'}
      </p>
      <ErrorText error={open.error} />
      {open.data && list.length === 0 && (
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Nothing waiting. New suggestions come with each digest.
        </p>
      )}
      <ul className="flex flex-col gap-3">
        {list.map((s) => (
          <SuggestionCard
            key={s.id}
            s={s}
            projectId={projectId}
            projectKey={projectKey}
            canApprove={canApprove}
            users={users}
          />
        ))}
      </ul>
      {automatic.length > 0 && (
        <div className="flex flex-col gap-1">
          <h3 className="font-semibold">Done on its own</h3>
          <ul aria-label="Done on its own" className="flex flex-col gap-1 text-sm">
            {automatic.map((s) => (
              <li key={s.id}>
                {s.result}
                {s.decided_at
                  ? `, ${new Date(s.decided_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}`
                  : ''}
                {canApprove && <UndoButton s={s} projectId={projectId} />}
              </li>
            ))}
          </ul>
        </div>
      )}
      {canApprove && <Notes projectId={projectId} />}
      <div>
        <GhostButton type="button" aria-expanded={showDecided} onClick={() => setShowDecided((v) => !v)}>
          {showDecided ? 'Hide recent decisions' : 'Show recent decisions'}
        </GhostButton>
      </div>
      {showDecided && decided.data && (
        <ul aria-label="Recent decisions" className="flex flex-col gap-1 text-sm">
          {decided.data.length === 0 && <li className="text-slate-600 dark:text-slate-400">None yet.</li>}
          {decided.data.map((s) => (
            <li key={s.id}>
              <strong>{STATUS[s.status]}</strong>: {KIND[s.kind]}
              {s.task ? ` · ${s.task.key}` : ''}
              {s.decided_by ? ` by ${s.decided_by}` : s.automatic ? ' automatically' : ''}
              {s.result ? ` (${s.result})` : ''}
              {canApprove && s.can_undo && <UndoButton s={s} projectId={projectId} />}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
