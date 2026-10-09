import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import {
  api,
  unwrap,
  type CustomField,
  type ProjectDetail,
  type Rule,
  type RuleAction,
  type RuleCondition,
  type RuleInput,
  type RuleTrigger,
  type Schemas,
  type User,
} from '../api/client';
import { TRIGGERS, triggerLabel, WEEKDAYS } from '../lib/automation';
import { Button, ErrorText, Field, GhostButton, Input, Select } from './ui';

type ActionType = Schemas['ActionType'];
type Operator = Schemas['Operator'];
type TriggerType = Schemas['TriggerType'];

const ACTIONS: { value: ActionType; label: string }[] = [
  { value: 'set_status', label: 'Set status' },
  { value: 'set_priority', label: 'Set priority' },
  { value: 'assign', label: 'Assign' },
  { value: 'unassign', label: 'Unassign' },
  { value: 'set_due_date', label: 'Set due date' },
  { value: 'add_tags', label: 'Add tags' },
  { value: 'remove_tags', label: 'Remove tags' },
  { value: 'set_custom_field', label: 'Set custom field' },
  { value: 'create_subtask', label: 'Create subtask' },
  { value: 'post_comment', label: 'Post comment' },
  { value: 'notify', label: 'Notify people' },
  { value: 'webhook', label: 'Call webhook' },
];
const OPERATORS: { value: Operator; label: string }[] = [
  { value: 'eq', label: 'is' },
  { value: 'neq', label: 'is not' },
  { value: 'in', label: 'is one of' },
  { value: 'not_in', label: 'is not one of' },
  { value: 'contains', label: 'contains' },
  { value: 'not_contains', label: 'does not contain' },
  { value: 'lt', label: 'less than' },
  { value: 'gt', label: 'greater than' },
  { value: 'is_empty', label: 'is empty' },
  { value: 'not_empty', label: 'is not empty' },
];
const PRIORITIES = ['none', 'low', 'medium', 'high', 'urgent'] as const;
const CATEGORIES = ['backlog', 'todo', 'in_progress', 'done', 'cancelled'] as const;
const PLACEHOLDERS =
  '{{task.key}} {{task.title}} {{task.status}} {{task.url}} {{project.name}} {{rule.name}}';

const blankRule = (): RuleInput => ({
  name: '',
  trigger: { type: 'status_changed', to_category: 'done' },
  conditions: [],
  actions: [{ type: 'add_tags', tags: [] }],
});

let nextRowKey = 0;
/** Keep one key per row: existing keys stay with their rows, new rows get new keys. */
function fitKeys(keys: string[], length: number): string[] {
  const out = keys.slice(0, length);
  while (out.length < length) out.push(`row-${++nextRowKey}`);
  return out;
}

function splitList(text: string): string[] {
  return text
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean);
}

/** Comma-separated list input that keeps the raw text while typing and follows outside changes. */
function ListInput({
  id,
  value,
  required,
  onChange,
}: {
  id: string;
  value: string[];
  required?: boolean;
  onChange: (items: string[]) => void;
}) {
  const [text, setText] = useState(value.join(', '));
  const joined = value.join('\n');
  const [seen, setSeen] = useState(joined);
  if (joined !== seen) {
    setSeen(joined);
    if (splitList(text).join('\n') !== joined) setText(value.join(', '));
  }
  return (
    <Input
      id={id}
      required={required}
      value={text}
      onChange={(e) => {
        setText(e.target.value);
        onChange(splitList(e.target.value));
      }}
    />
  );
}

function ConditionRow({
  value,
  fields,
  index,
  onChange,
  onRemove,
}: {
  value: RuleCondition;
  fields: CustomField[];
  index: number;
  onChange: (c: RuleCondition) => void;
  onRemove: () => void;
}) {
  const id = `cond-${index}`;
  const noValue = value.op === 'is_empty' || value.op === 'not_empty';
  return (
    <li className="flex flex-wrap items-end gap-2">
      <Field label="Field" id={`${id}-field`}>
        <Select
          id={`${id}-field`}
          value={value.field}
          onChange={(e) => onChange({ ...value, field: e.target.value })}
        >
          <option value="priority">Priority</option>
          <option value="status_category">Status category</option>
          <option value="assignee_id">Assignee</option>
          <option value="tags">Tags</option>
          <option value="title">Title</option>
          <option value="due_in_days">Days until due</option>
          <option value="is_subtask">Is a subtask</option>
          {fields.map((f) => (
            <option key={f.id} value={`cf:${f.id}`}>
              {f.name}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Operator" id={`${id}-op`}>
        <Select
          id={`${id}-op`}
          value={value.op}
          onChange={(e) => onChange({ ...value, op: e.target.value as Operator })}
        >
          {OPERATORS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
      </Field>
      {!noValue && (
        <Field label="Value" id={`${id}-value`}>
          {value.op === 'in' || value.op === 'not_in' ? (
            <ListInput
              key={value.op}
              id={`${id}-value`}
              value={Array.isArray(value.value) ? value.value.map(String) : []}
              onChange={(items) => onChange({ ...value, value: items })}
            />
          ) : (
            <Input
              id={`${id}-value`}
              value={Array.isArray(value.value) ? value.value.join(', ') : String(value.value ?? '')}
              onChange={(e) => onChange({ ...value, value: e.target.value })}
            />
          )}
        </Field>
      )}
      <GhostButton aria-label={`Remove condition ${index + 1}`} onClick={onRemove}>
        ✕
      </GhostButton>
    </li>
  );
}

function ActionRow({
  value,
  index,
  project,
  fields,
  users,
  onChange,
  onRemove,
}: {
  value: RuleAction;
  index: number;
  project: ProjectDetail;
  fields: CustomField[];
  users: User[];
  onChange: (a: RuleAction) => void;
  onRemove: () => void;
}) {
  const id = `act-${index}`;
  const set = (patch: Partial<RuleAction>) => onChange({ ...value, ...patch });
  const text = (key: 'title' | 'body' | 'url', label: string, required = true) => (
    <Field label={label} id={`${id}-${key}`}>
      <Input
        id={`${id}-${key}`}
        required={required}
        className="min-w-64"
        value={value[key] ?? ''}
        onChange={(e) => set({ [key]: e.target.value })}
      />
    </Field>
  );
  return (
    <li className="flex flex-wrap items-end gap-2">
      <Field label="Action" id={`${id}-type`}>
        <Select
          id={`${id}-type`}
          value={value.type}
          onChange={(e) => onChange({ type: e.target.value as ActionType })}
        >
          {ACTIONS.map((a) => (
            <option key={a.value} value={a.value}>
              {a.label}
            </option>
          ))}
        </Select>
      </Field>
      {value.type === 'set_status' && (
        <Field label="Status" id={`${id}-status`}>
          <Select
            id={`${id}-status`}
            required
            value={value.status_id ?? ''}
            onChange={(e) => set({ status_id: e.target.value })}
          >
            <option value="">Choose…</option>
            {project.statuses.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </Select>
        </Field>
      )}
      {value.type === 'set_priority' && (
        <Field label="Priority" id={`${id}-priority`}>
          <Select
            id={`${id}-priority`}
            value={value.priority ?? 'none'}
            onChange={(e) => set({ priority: e.target.value as RuleAction['priority'] })}
          >
            {PRIORITIES.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </Select>
        </Field>
      )}
      {value.type === 'assign' && (
        <Field label="Assignee" id={`${id}-user`}>
          <Select
            id={`${id}-user`}
            required
            value={value.user ?? ''}
            onChange={(e) => set({ user: e.target.value })}
          >
            <option value="">Choose…</option>
            <option value="reporter">The reporter</option>
            <option value="actor">Whoever made the change</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </Select>
        </Field>
      )}
      {value.type === 'set_due_date' && (
        <Field label="Days from today" id={`${id}-days`}>
          <Input
            id={`${id}-days`}
            type="number"
            required
            className="w-24"
            value={value.days_from_now ?? ''}
            onChange={(e) => set({ days_from_now: Number(e.target.value) })}
          />
        </Field>
      )}
      {(value.type === 'add_tags' || value.type === 'remove_tags') && (
        <Field label="Tags (comma separated)" id={`${id}-tags`}>
          <ListInput id={`${id}-tags`} required value={value.tags ?? []} onChange={(tags) => set({ tags })} />
        </Field>
      )}
      {value.type === 'set_custom_field' && (
        <>
          <Field label="Field" id={`${id}-field`}>
            <Select
              id={`${id}-field`}
              required
              value={value.field_id ?? ''}
              onChange={(e) => set({ field_id: e.target.value })}
            >
              <option value="">Choose…</option>
              {fields.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Value" id={`${id}-fvalue`}>
            <Input
              id={`${id}-fvalue`}
              value={String(value.value ?? '')}
              onChange={(e) => set({ value: e.target.value })}
            />
          </Field>
        </>
      )}
      {value.type === 'create_subtask' && text('title', 'Subtask title')}
      {value.type === 'post_comment' && text('body', 'Comment')}
      {value.type === 'notify' && (
        <>
          <Field label="Who" id={`${id}-users`}>
            <Select
              id={`${id}-users`}
              multiple
              required
              value={value.users ?? []}
              onChange={(e) => set({ users: Array.from(e.target.selectedOptions, (o) => o.value) })}
            >
              <option value="assignee">The assignee</option>
              <option value="reporter">The reporter</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
            </Select>
          </Field>
          {text('title', 'Message')}
        </>
      )}
      {value.type === 'webhook' && text('url', 'URL (POST, JSON)')}
      <GhostButton aria-label={`Remove action ${index + 1}`} onClick={onRemove}>
        ✕
      </GhostButton>
    </li>
  );
}

function TriggerEditor({ value, onChange }: { value: RuleTrigger; onChange: (t: RuleTrigger) => void }) {
  const schedule = value.schedule ?? { frequency: 'weekly', weekday: 0, hour: 9, minute: 0 };
  const setSchedule = (patch: Partial<typeof schedule>) =>
    onChange({ ...value, schedule: { ...schedule, ...patch } });
  return (
    <div className="flex flex-wrap items-end gap-2">
      <Field label="When" id="trigger-type">
        <Select
          id="trigger-type"
          value={value.type}
          onChange={(e) => {
            const type = e.target.value as TriggerType;
            onChange({
              type,
              ...(type === 'due_soon' ? { days_before: 1 } : {}),
              ...(type === 'scheduled'
                ? {
                    schedule: {
                      frequency: 'weekly',
                      weekday: 0,
                      hour: 9,
                      minute: 0,
                      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                    },
                  }
                : {}),
            });
          }}
        >
          {TRIGGERS.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </Select>
      </Field>
      {value.type === 'status_changed' && (
        <Field label="To category" id="trigger-cat">
          <Select
            id="trigger-cat"
            value={value.to_category ?? ''}
            onChange={(e) =>
              onChange({ ...value, to_category: (e.target.value || null) as RuleTrigger['to_category'] })
            }
          >
            <option value="">Any status</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c.replace('_', ' ')}
              </option>
            ))}
          </Select>
        </Field>
      )}
      {value.type === 'task_updated' && (
        <Field label="Field changed" id="trigger-field">
          <Select
            id="trigger-field"
            value={value.field ?? ''}
            onChange={(e) => onChange({ ...value, field: (e.target.value || null) as RuleTrigger['field'] })}
          >
            <option value="">Any field</option>
            {['status_id', 'priority', 'assignee_id', 'due_date', 'start_date', 'title', 'tags'].map((f) => (
              <option key={f} value={f}>
                {f.replace('_id', '').replace('_', ' ')}
              </option>
            ))}
          </Select>
        </Field>
      )}
      {value.type === 'due_soon' && (
        <Field label="Days before due" id="trigger-days">
          <Input
            id="trigger-days"
            type="number"
            min={0}
            max={365}
            className="w-24"
            value={value.days_before ?? 1}
            onChange={(e) => onChange({ ...value, days_before: Number(e.target.value) })}
          />
        </Field>
      )}
      {value.type === 'scheduled' && (
        <ScheduleFields value={schedule} onChange={setSchedule} idPrefix="trigger" />
      )}
    </div>
  );
}

export function ScheduleFields({
  value,
  onChange,
  idPrefix,
}: {
  value: Schemas['ScheduleSpec-Input'];
  onChange: (patch: Partial<Schemas['ScheduleSpec-Input']>) => void;
  idPrefix: string;
}) {
  return (
    <>
      <Field label="Repeat" id={`${idPrefix}-freq`}>
        <Select
          id={`${idPrefix}-freq`}
          value={value.frequency}
          onChange={(e) => {
            const frequency = e.target.value as typeof value.frequency;
            onChange({
              frequency,
              weekday: frequency === 'weekly' ? (value.weekday ?? 0) : null,
              day: frequency === 'monthly' ? (value.day ?? 1) : null,
            });
          }}
        >
          <option value="daily">Daily</option>
          <option value="weekly">Weekly</option>
          <option value="monthly">Monthly</option>
        </Select>
      </Field>
      {value.frequency === 'weekly' && (
        <Field label="On" id={`${idPrefix}-weekday`}>
          <Select
            id={`${idPrefix}-weekday`}
            value={value.weekday ?? 0}
            onChange={(e) => onChange({ weekday: Number(e.target.value) })}
          >
            {WEEKDAYS.map((d, i) => (
              <option key={d} value={i}>
                {d}
              </option>
            ))}
          </Select>
        </Field>
      )}
      {value.frequency === 'monthly' && (
        <Field label="Day of month" id={`${idPrefix}-day`}>
          <Input
            id={`${idPrefix}-day`}
            type="number"
            min={1}
            max={28}
            className="w-20"
            value={value.day ?? 1}
            onChange={(e) => onChange({ day: Number(e.target.value) })}
          />
        </Field>
      )}
      <Field label="Time" id={`${idPrefix}-time`}>
        <Input
          id={`${idPrefix}-time`}
          type="time"
          value={`${String(value.hour ?? 9).padStart(2, '0')}:${String(value.minute ?? 0).padStart(2, '0')}`}
          onChange={(e) => {
            const [h, m] = e.target.value.split(':').map(Number);
            onChange({ hour: h ?? 9, minute: m ?? 0 });
          }}
        />
      </Field>
      <p className="self-center text-xs text-slate-600 dark:text-slate-400">{value.timezone ?? 'UTC'}</p>
    </>
  );
}

function RunLog({ projectId, rules }: { projectId: string; rules: Rule[] }) {
  const queryClient = useQueryClient();
  const runs = useQuery({
    queryKey: ['automation-runs', projectId],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/projects/{project_id}/automation-runs', {
          params: { path: { project_id: projectId }, query: { limit: 50 } },
        }),
      ),
    refetchInterval: 15_000,
  });
  const retry = useMutation({
    mutationFn: (runId: string) =>
      unwrap(api.POST('/api/v1/automation-runs/{run_id}/retry', { params: { path: { run_id: runId } } })),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['automation-runs', projectId] }),
  });
  if (rules.length === 0) return null;
  return (
    <section aria-labelledby="runs-h" className="flex flex-col gap-2">
      <h3 id="runs-h" className="font-semibold">
        Recent runs
      </h3>
      {runs.data?.length === 0 && <p className="text-sm text-slate-600 dark:text-slate-400">No runs yet.</p>}
      {!!runs.data?.length && (
        <table className="w-full text-left text-sm">
          <thead className="text-xs text-slate-600 dark:text-slate-400">
            <tr>
              <th className="py-1 font-medium">When</th>
              <th className="font-medium">Rule</th>
              <th className="font-medium">Task</th>
              <th className="font-medium">Result</th>
              <th />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {runs.data.map((r) => (
              <tr key={r.id}>
                <td className="py-1.5 whitespace-nowrap">{new Date(r.started_at).toLocaleString()}</td>
                <td>{r.rule_name}</td>
                <td className="font-mono text-xs whitespace-nowrap">{String(r.results.task_key ?? '—')}</td>
                <td>
                  <span
                    className={
                      r.status === 'failed'
                        ? 'text-red-700 dark:text-red-400'
                        : 'text-emerald-700 dark:text-emerald-400'
                    }
                  >
                    {r.status === 'success' && !r.finished_at ? 'sending…' : r.status}
                  </span>
                  {r.error && (
                    <span className="block text-xs text-slate-600 dark:text-slate-400">{r.error}</span>
                  )}
                </td>
                <td className="text-right">
                  {r.status === 'failed' && (
                    <GhostButton
                      aria-label={`Retry run of ${r.rule_name}`}
                      disabled={retry.isPending}
                      onClick={() => retry.mutate(r.id)}
                    >
                      Retry
                    </GhostButton>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <ErrorText error={retry.error} />
    </section>
  );
}

export function AutomationRules({
  project,
  fields,
  users,
}: {
  project: ProjectDetail;
  fields: CustomField[];
  users: User[];
}) {
  const queryClient = useQueryClient();
  const key = ['automation-rules', project.id];
  const rules = useQuery({
    queryKey: key,
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/projects/{project_id}/automation-rules', {
          params: { path: { project_id: project.id } },
        }),
      ),
  });
  const [draft, setDraftState] = useState<RuleInput | null>(null);
  // Stable keys for condition and action rows, so removing one never shows another's values.
  const [rowKeys, setRowKeys] = useState<{ conditions: string[]; actions: string[] }>({
    conditions: [],
    actions: [],
  });
  const setDraft = (next: RuleInput | null) => {
    setDraftState(next);
    setRowKeys((keys) => ({
      conditions: fitKeys(keys.conditions, next?.conditions?.length ?? 0),
      actions: fitKeys(keys.actions, next?.actions.length ?? 0),
    }));
  };
  const startDraft = (next: RuleInput) => {
    setDraftState(next);
    setRowKeys({
      conditions: fitKeys([], next.conditions?.length ?? 0),
      actions: fitKeys([], next.actions.length),
    });
  };
  const removeRow = (list: 'conditions' | 'actions', index: number, next: RuleInput) => {
    setDraftState(next);
    setRowKeys((keys) => ({ ...keys, [list]: keys[list].filter((_, j) => j !== index) }));
  };
  const [editing, setEditing] = useState<string | null>(null);
  const [testTask, setTestTask] = useState('');
  const refresh = () => void queryClient.invalidateQueries({ queryKey: key });

  const save = useMutation({
    mutationFn: (rule: RuleInput) =>
      editing
        ? unwrap(
            api.PATCH('/api/v1/automation-rules/{rule_id}', {
              params: { path: { rule_id: editing } },
              body: rule,
            }),
          )
        : unwrap(
            api.POST('/api/v1/projects/{project_id}/automation-rules', {
              params: { path: { project_id: project.id } },
              body: rule,
            }),
          ),
    onSuccess: () => {
      setDraft(null);
      setEditing(null);
      refresh();
    },
  });
  const toggle = useMutation({
    mutationFn: (rule: Rule) =>
      unwrap(
        api.PATCH('/api/v1/automation-rules/{rule_id}', {
          params: { path: { rule_id: rule.id } },
          body: { enabled: !rule.enabled },
        }),
      ),
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: (ruleId: string) =>
      unwrap(api.DELETE('/api/v1/automation-rules/{rule_id}', { params: { path: { rule_id: ruleId } } })),
    onSettled: refresh,
  });
  const test = useMutation({
    mutationFn: (rule: RuleInput) =>
      unwrap(
        api.POST('/api/v1/projects/{project_id}/automation-rules/test', {
          params: { path: { project_id: project.id } },
          body: { rule, task: testTask.trim() },
        }),
      ),
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (draft) save.mutate(draft);
  };

  return (
    <div className="flex flex-col gap-4">
      <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
        {rules.data?.length === 0 && (
          <li className="p-3 text-sm text-slate-600 dark:text-slate-400">
            No rules yet. Rules run on their own when something happens, e.g. “when a task moves to Done,
            notify the reporter”.
          </li>
        )}
        {rules.data?.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 p-3 text-sm">
            <span>
              <span
                className={`font-medium ${r.enabled ? '' : 'text-slate-500 dark:text-slate-400 line-through'}`}
              >
                {r.name}
              </span>{' '}
              <span className="text-slate-600 dark:text-slate-400">
                {triggerLabel(r.trigger)} · {r.actions.length} action{r.actions.length === 1 ? '' : 's'}
                {r.last_run_at && ` · last ran ${new Date(r.last_run_at).toLocaleString()}`}
              </span>
              {r.webhook_secret && r.actions.some((a) => a.type === 'webhook') && (
                <details className="mt-1 text-xs">
                  <summary className="cursor-pointer text-slate-600 dark:text-slate-400">
                    Signing secret
                  </summary>
                  <code className="break-all">{r.webhook_secret}</code>
                </details>
              )}
            </span>
            <span className="flex gap-2">
              <GhostButton
                aria-label={`${r.enabled ? 'Disable' : 'Enable'} ${r.name}`}
                onClick={() => toggle.mutate(r)}
              >
                {r.enabled ? 'Disable' : 'Enable'}
              </GhostButton>
              <GhostButton
                aria-label={`Edit ${r.name}`}
                onClick={() => {
                  setEditing(r.id);
                  startDraft({
                    name: r.name,
                    enabled: r.enabled,
                    trigger: r.trigger,
                    conditions: r.conditions,
                    actions: r.actions,
                    run_on_automation: r.run_on_automation,
                  });
                }}
              >
                Edit
              </GhostButton>
              <GhostButton
                aria-label={`Delete ${r.name}`}
                onClick={() => window.confirm(`Delete the rule "${r.name}"?`) && remove.mutate(r.id)}
              >
                Delete
              </GhostButton>
            </span>
          </li>
        ))}
      </ul>
      <ErrorText error={toggle.error ?? remove.error} />

      {!draft ? (
        <div>
          <Button
            onClick={() => {
              setEditing(null);
              startDraft(blankRule());
            }}
          >
            New rule
          </Button>
        </div>
      ) : (
        <form
          aria-label={editing ? 'Edit rule' : 'New rule'}
          onSubmit={onSubmit}
          className="flex flex-col gap-4 rounded-lg border border-slate-200 p-4 dark:border-slate-800"
        >
          <Field label="Rule name" id="rule-name">
            <Input
              id="rule-name"
              required
              maxLength={100}
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </Field>
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-sm font-semibold">Trigger</legend>
            <TriggerEditor value={draft.trigger} onChange={(trigger) => setDraft({ ...draft, trigger })} />
          </fieldset>
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-sm font-semibold">Only if (all must match)</legend>
            <ul className="flex flex-col gap-2">
              {(draft.conditions ?? []).map((c, i) => (
                <ConditionRow
                  key={rowKeys.conditions[i] ?? i}
                  index={i}
                  value={c}
                  fields={fields}
                  onChange={(next) =>
                    setDraft({
                      ...draft,
                      conditions: (draft.conditions ?? []).map((x, j) => (j === i ? next : x)),
                    })
                  }
                  onRemove={() =>
                    removeRow('conditions', i, {
                      ...draft,
                      conditions: (draft.conditions ?? []).filter((_, j) => j !== i),
                    })
                  }
                />
              ))}
            </ul>
            <div>
              <GhostButton
                onClick={() =>
                  setDraft({
                    ...draft,
                    conditions: [...(draft.conditions ?? []), { field: 'priority', op: 'eq', value: 'high' }],
                  })
                }
              >
                Add condition
              </GhostButton>
            </div>
          </fieldset>
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-sm font-semibold">Then</legend>
            <ul className="flex flex-col gap-2">
              {draft.actions.map((a, i) => (
                <ActionRow
                  key={rowKeys.actions[i] ?? i}
                  index={i}
                  value={a}
                  project={project}
                  fields={fields}
                  users={users}
                  onChange={(next) =>
                    setDraft({ ...draft, actions: draft.actions.map((x, j) => (j === i ? next : x)) })
                  }
                  onRemove={() =>
                    removeRow('actions', i, { ...draft, actions: draft.actions.filter((_, j) => j !== i) })
                  }
                />
              ))}
            </ul>
            <p className="text-xs text-slate-600 dark:text-slate-400">Text can use {PLACEHOLDERS}</p>
            <div>
              <GhostButton
                onClick={() =>
                  setDraft({ ...draft, actions: [...draft.actions, { type: 'post_comment', body: '' }] })
                }
              >
                Add action
              </GhostButton>
            </div>
          </fieldset>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={draft.run_on_automation ?? false}
              onChange={(e) => setDraft({ ...draft, run_on_automation: e.target.checked })}
            />
            Also react to changes made by other automations
          </label>
          <div className="flex flex-wrap items-end gap-2 border-t border-slate-200 pt-3 dark:border-slate-800">
            <Field label="Test against task (e.g. WEB-12)" id="rule-test-task">
              <Input id="rule-test-task" value={testTask} onChange={(e) => setTestTask(e.target.value)} />
            </Field>
            <GhostButton disabled={!testTask.trim() || test.isPending} onClick={() => test.mutate(draft)}>
              Dry run
            </GhostButton>
          </div>
          {test.data && (
            <div role="status" className="rounded-md bg-slate-50 p-3 text-sm dark:bg-slate-900">
              <p className="font-medium">
                {test.data.matched
                  ? 'Conditions match — it would:'
                  : 'Conditions do not match — nothing would happen.'}
              </p>
              {test.data.matched && (
                <ul className="list-disc pl-5">
                  {test.data.planned_actions.map((a) => (
                    <li key={a}>{a}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
          <ErrorText error={save.error ?? test.error} />
          <div className="flex gap-2">
            <Button type="submit" disabled={save.isPending || draft.actions.length === 0}>
              {editing ? 'Save rule' : 'Create rule'}
            </Button>
            <GhostButton
              onClick={() => {
                setDraft(null);
                setEditing(null);
                test.reset();
              }}
            >
              Cancel
            </GhostButton>
          </div>
        </form>
      )}
      <RunLog projectId={project.id} rules={rules.data ?? []} />
    </div>
  );
}
