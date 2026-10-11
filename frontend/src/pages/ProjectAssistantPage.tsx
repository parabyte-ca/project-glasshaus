import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useId, useState, type ReactNode } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';

import { api, unwrap, type Schemas } from '../api/client';
import { AssistantSuggestions } from '../components/AssistantSuggestions';
import { Markdown } from '../components/Markdown';
import { LoadError } from '../components/PageState';
import {
  Button,
  CopyButton,
  ErrorText,
  Field,
  GhostButton,
  Input,
  linkClass,
  Select,
} from '../components/ui';
import { WEEKDAYS } from '../lib/automation';
import { useConfirm } from '../lib/confirm';
import { useUnsavedGuard } from '../lib/unsaved';
import { usePageTitle } from '../lib/pageTitle';
import { toast } from '../lib/toast';
import { useProject } from '../lib/useProject';

type Settings = {
  enabled: boolean;
  timezone: string;
  digest: Schemas['DigestSettings-Output'];
  weekly: Schemas['WeeklySettings-Output'];
  stale_days: number;
  delivery: Schemas['DeliverySettings-Output'];
  suggestions: boolean;
  trusted: 'comment'[];
  auto_daily_cap: number;
};
type Brief = Schemas['BriefRead'];
type BriefTask = Schemas['BriefTask'];

const HEALTH: Record<string, string> = { on_track: 'On track', at_risk: 'At risk', off_track: 'Off track' };

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });

const hhmm = (h: number, m = 0) => `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;

const days = (n: number) => `${n} day${n === 1 ? '' : 's'}`;

function defaults(): Settings {
  return {
    enabled: true,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
    digest: { enabled: true, hour: 8, minute: 0, weekdays_only: true },
    weekly: { enabled: true, weekday: 4, hour: 14 },
    stale_days: 5,
    delivery: { in_app: true, email: false, channel_id: null },
    suggestions: true,
    trusted: [],
    auto_daily_cap: 10,
  };
}

/** Only the editable settings: the saved settings also carry read-only fields the API rejects. */
function writable(v: Settings): Settings {
  return {
    enabled: v.enabled,
    timezone: v.timezone,
    digest: v.digest,
    weekly: v.weekly,
    stale_days: v.stale_days,
    delivery: v.delivery,
    suggestions: v.suggestions,
    trusted: v.trusted,
    auto_daily_cap: v.auto_daily_cap,
  };
}

function timezones(current: string): string[] {
  const all = typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : ['UTC'];
  return all.includes(current) ? all : [current, ...all];
}

/** The project assistant: today's stand-up digest, weekly status drafts and (for admins) settings. */
export function ProjectAssistantPage() {
  const { projectKey = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const { project, users } = useProject(projectKey);
  const projectId = project.data?.id ?? '';
  usePageTitle(project.data ? `Project assistant · ${project.data.name}` : 'Project assistant');
  const path = { params: { path: { project_id: projectId } } };
  const status = useQuery({
    queryKey: ['assistant', projectId],
    enabled: !!projectId,
    queryFn: () => unwrap(api.GET('/api/v1/projects/{project_id}/assistant', path)),
  });
  const briefs = useQuery({
    queryKey: ['assistant-briefs', projectId],
    enabled: !!projectId,
    queryFn: () => unwrap(api.GET('/api/v1/projects/{project_id}/assistant/briefs', path)),
  });
  const chosen = params.get('brief') ?? briefs.data?.[0]?.id ?? null;
  const brief = useQuery({
    queryKey: ['assistant-brief', chosen],
    enabled: !!chosen,
    queryFn: () =>
      unwrap(api.GET('/api/v1/assistant/briefs/{brief_id}', { params: { path: { brief_id: chosen! } } })),
  });

  if (project.isError)
    return <LoadError error={project.error} what="project" onRetry={() => void project.refetch()} />;
  if (!project.data || !status.data)
    return (
      <>
        <ErrorText error={status.error} />
        {!status.error && <p role="status">Loading…</p>}
      </>
    );
  const s = status.data;
  return (
    <div className="flex max-w-5xl flex-col gap-6">
      <div>
        <Link to={`/projects/${projectKey}`} className={`text-sm ${linkClass}`}>
          ← {project.data.name}
        </Link>
        <h1 className="text-2xl font-bold">Project assistant</h1>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          The project assistant writes a daily stand-up digest for everyone on the project and a weekly status
          draft for its admins. It only reads the project; it never changes anything.
        </p>
      </div>
      {!s.settings && !s.can_manage && (
        <p className="text-sm">A project admin can turn the assistant on for this project.</p>
      )}
      <div className="grid gap-6 md:grid-cols-[1fr_16rem]">
        <div className="min-w-0">
          {brief.data ? (
            <BriefView brief={brief.data} projectKey={projectKey} />
          ) : briefs.data && briefs.data.length === 0 ? (
            <p className="text-slate-600 dark:text-slate-400">
              Nothing yet. The first digest arrives at the next scheduled time
              {s.can_manage && s.settings ? ', or use Write a digest now below' : ''}.
            </p>
          ) : (
            <ErrorText error={brief.error ?? briefs.error} />
          )}
        </div>
        {briefs.data && briefs.data.length > 0 && (
          <nav aria-label="Earlier digests and drafts">
            <h2 className="mb-2 font-semibold">Earlier</h2>
            <ul className="flex flex-col gap-1 text-sm">
              {briefs.data.map((b) => (
                <li key={b.id}>
                  <button
                    type="button"
                    aria-current={b.id === chosen ? 'true' : undefined}
                    onClick={() => setParams({ brief: b.id })}
                    className={`w-full rounded px-2 py-1 text-left hover:bg-slate-100 dark:hover:bg-slate-800 ${b.id === chosen ? 'bg-slate-100 font-medium dark:bg-slate-800' : ''}`}
                  >
                    <span className="block">{b.kind === 'weekly' ? 'Weekly draft' : 'Digest'}</span>
                    <span className="text-xs text-slate-600 dark:text-slate-400">{when(b.created_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </nav>
        )}
      </div>
      {s.settings?.enabled && (
        <AssistantSuggestions
          projectId={projectId}
          projectKey={projectKey}
          canApprove={s.can_approve}
          users={users}
        />
      )}
      {s.can_manage && (
        <AssistantSettings projectId={projectId} status={s} onWritten={(id) => setParams({ brief: id })} />
      )}
    </div>
  );
}

function TaskList({
  items,
  projectKey,
  extra,
}: {
  items: BriefTask[];
  projectKey: string;
  extra?: (t: BriefTask) => string;
}) {
  return (
    <ul className="flex flex-col gap-1 text-sm">
      {items.map((t) => (
        <li key={t.key}>
          <Link className={`font-mono ${linkClass}`} to={`/projects/${projectKey}?task=${t.key}`}>
            {t.key}
          </Link>{' '}
          {t.title}
          <span className="text-slate-600 dark:text-slate-400">
            {t.assignee ? ` · ${t.assignee}` : ''}
            {extra ? ` · ${extra(t)}` : ''}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Part({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="flex flex-col gap-1">
      <h3 id={id} className="font-semibold">
        {title}
      </h3>
      {children}
    </section>
  );
}

function asText(b: Brief): string {
  const c = b.content;
  const lines = [b.title, ''];
  if (c.headline) lines.push(c.headline, '');
  if (c.summary) lines.push(c.summary, '');
  for (const [h, items] of [
    ['Highlights', c.highlights],
    ['Concerns', c.concerns],
  ] as const)
    if (items.length) lines.push(h, ...items.map((x) => `- ${x}`), '');
  if (c.overdue_tasks.length)
    lines.push('Overdue', ...c.overdue_tasks.map((t) => `- ${t.key} ${t.title}`), '');
  if (c.completed.length) lines.push('Completed', ...c.completed.map((t) => `- ${t.key} ${t.title}`), '');
  return lines.join('\n').trim();
}

function BriefView({ brief, projectKey }: { brief: Brief; projectKey: string }) {
  const c = brief.content;
  const late = (t: BriefTask) => `${days(t.days ?? 0)} late`;
  const due = (t: BriefTask) =>
    t.due_date
      ? `due ${new Date(`${t.due_date}T00:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`
      : '';
  return (
    <article aria-labelledby="brief-h" className="flex flex-col gap-4">
      <header>
        <h2 id="brief-h" className="text-lg font-semibold">
          {brief.title}
        </h2>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          {when(brief.created_at)} · {HEALTH[c.health] ?? c.health} · {c.progress}% complete · Open {c.open} ·
          Overdue {c.overdue}
        </p>
        <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
          {c.ai_model
            ? 'Written by the project assistant (AI). Check before acting; it can be wrong.'
            : c.ai_note}
        </p>
      </header>
      {c.headline && <p className="font-medium">{c.headline}</p>}
      {c.summary && <Markdown text={c.summary} />}
      {c.focus.length > 0 && (
        <Part title="Focus today">
          <ul className="list-disc pl-5 text-sm">
            {c.focus.map((f, i) => (
              <li key={i}>
                {f.text}
                {f.task_key && (
                  <>
                    {' '}
                    <Link
                      className={`font-mono ${linkClass}`}
                      to={`/projects/${projectKey}?task=${f.task_key}`}
                    >
                      {f.task_key}
                    </Link>
                  </>
                )}
              </li>
            ))}
          </ul>
        </Part>
      )}
      {(
        [
          ['Highlights', c.highlights],
          ['Concerns', c.concerns],
        ] as const
      ).map(
        ([title, items]) =>
          items.length > 0 && (
            <Part key={title} title={title}>
              <ul className="list-disc pl-5 text-sm">
                {items.map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ul>
            </Part>
          ),
      )}
      {brief.kind === 'weekly' && (
        <div>
          <CopyButton value={asText(brief)} label="Copy draft as text" />
        </div>
      )}
      {c.overdue_tasks.length > 0 && (
        <Part title="Overdue">
          <TaskList items={c.overdue_tasks} projectKey={projectKey} extra={late} />
        </Part>
      )}
      {c.due_today.length > 0 && (
        <Part title="Due today">
          <TaskList items={c.due_today} projectKey={projectKey} />
        </Part>
      )}
      {c.due_soon.length > 0 && (
        <Part title="Due soon">
          <TaskList items={c.due_soon} projectKey={projectKey} extra={due} />
        </Part>
      )}
      {c.stale.length > 0 && (
        <Part title={`No update for ${c.stale_days}+ days`}>
          <TaskList items={c.stale} projectKey={projectKey} extra={(t) => days(t.days ?? 0)} />
        </Part>
      )}
      {c.unassigned.length > 0 && (
        <Part title="Unassigned and due soon">
          <TaskList items={c.unassigned} projectKey={projectKey} extra={due} />
        </Part>
      )}
      {c.completed.length > 0 && (
        <Part title={brief.kind === 'weekly' ? 'Completed' : 'Done since the last digest'}>
          <TaskList items={c.completed} projectKey={projectKey} />
        </Part>
      )}
      {c.warnings.length > 0 && (
        <Part title="Schedule warnings">
          <ul className="list-disc pl-5 text-sm">
            {c.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </Part>
      )}
    </article>
  );
}

function AssistantSettings({
  projectId,
  status,
  onWritten,
}: {
  projectId: string;
  status: Schemas['AssistantStatus'];
  onWritten: (briefId: string) => void;
}) {
  const id = useId();
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const saved = status.settings;
  const [draft, setDraft] = useState<Settings | null>(null);
  useUnsavedGuard(draft !== null);
  const v: Settings = draft ?? saved ?? defaults();
  const set = (patch: Partial<Settings>) => setDraft({ ...v, ...patch });
  const path = { params: { path: { project_id: projectId } } };
  const refresh = async () => {
    setDraft(null);
    await queryClient.invalidateQueries({ queryKey: ['assistant', projectId] });
    await queryClient.invalidateQueries({ queryKey: ['assistant-briefs', projectId] });
    await queryClient.invalidateQueries({ queryKey: ['members', projectId] });
    await queryClient.invalidateQueries({ queryKey: ['suggestions', projectId] });
  };
  const save = useMutation({
    mutationFn: () =>
      unwrap(api.PUT('/api/v1/projects/{project_id}/assistant', { ...path, body: writable(v) })),
    onSuccess: async (r) => {
      toast(
        r.enabled
          ? r.next_digest_at
            ? `Assistant saved. Next digest: ${when(r.next_digest_at)}`
            : 'Assistant saved'
          : 'Assistant turned off',
      );
      await refresh();
    },
  });
  const remove = useMutation({
    mutationFn: () => unwrap(api.DELETE('/api/v1/projects/{project_id}/assistant', path)),
    onSuccess: async () => {
      toast('Assistant removed from the project');
      await refresh();
    },
  });
  const run = useMutation({
    mutationFn: (kind: 'digest' | 'weekly') =>
      unwrap(api.POST('/api/v1/projects/{project_id}/assistant/run', { ...path, body: { kind } })),
    onSuccess: async (b) => {
      toast('Written. Nobody was notified; it is on this page.');
      await refresh();
      onWritten(b.id);
    },
  });
  const channels = status.channels;
  return (
    <section
      aria-labelledby={`${id}-h`}
      className="flex flex-col gap-4 rounded-lg border border-slate-200 p-4 dark:border-slate-800"
    >
      <div>
        <h2 id={`${id}-h`} className="text-lg font-semibold">
          Assistant settings
        </h2>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          {saved
            ? saved.enabled
              ? `On. ${saved.next_digest_at ? `Next digest ${when(saved.next_digest_at)}. ` : ''}${saved.next_weekly_at ? `Next weekly draft ${when(saved.next_weekly_at)}.` : ''}`
              : 'Off. Turn it back on to resume digests.'
            : `Turning it on adds “${status.account_name}” to the project as a Viewer. It cannot sign in, be assigned work or change anything.`}
        </p>
        {!status.ai && (
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            AI write-ups are off, so digests list the facts only. An organization admin can allow “Project
            assistant” under Admin › AI.
          </p>
        )}
        {saved?.last_error && (
          <p role="alert" className="mt-1 text-sm text-red-700 dark:text-red-400">
            Last run had a problem: {saved.last_error}
          </p>
        )}
      </div>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <label className="flex items-center gap-2 text-sm font-medium">
          <input type="checkbox" checked={v.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
          Assistant on for this project
        </label>
        <fieldset className="flex flex-wrap items-end gap-3">
          <legend className="mb-1 text-sm font-semibold">
            Daily stand-up digest (everyone on the project)
          </legend>
          <label className="flex items-center gap-2 self-center text-sm">
            <input
              type="checkbox"
              checked={v.digest.enabled}
              onChange={(e) => set({ digest: { ...v.digest, enabled: e.target.checked } })}
            />
            Send
          </label>
          <Field label="Time" id={`${id}-dtime`}>
            <Input
              id={`${id}-dtime`}
              type="time"
              value={hhmm(v.digest.hour ?? 8, v.digest.minute ?? 0)}
              onChange={(e) => {
                if (!e.target.value) return; // cleared: keep the saved time
                const [h, m] = e.target.value.split(':').map(Number);
                set({ digest: { ...v.digest, hour: h ?? 8, minute: m ?? 0 } });
              }}
            />
          </Field>
          <label className="flex items-center gap-2 self-center text-sm">
            <input
              type="checkbox"
              checked={v.digest.weekdays_only ?? true}
              onChange={(e) => set({ digest: { ...v.digest, weekdays_only: e.target.checked } })}
            />
            Weekdays only
          </label>
        </fieldset>
        <fieldset className="flex flex-wrap items-end gap-3">
          <legend className="mb-1 text-sm font-semibold">Weekly status draft (project admins)</legend>
          <label className="flex items-center gap-2 self-center text-sm">
            <input
              type="checkbox"
              checked={v.weekly.enabled}
              onChange={(e) => set({ weekly: { ...v.weekly, enabled: e.target.checked } })}
            />
            Write
          </label>
          <Field label="On" id={`${id}-wday`}>
            <Select
              id={`${id}-wday`}
              value={v.weekly.weekday ?? 4}
              onChange={(e) => set({ weekly: { ...v.weekly, weekday: Number(e.target.value) } })}
            >
              {WEEKDAYS.map((d, i) => (
                <option key={d} value={i}>
                  {d}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="At" id={`${id}-whour`}>
            <Input
              id={`${id}-whour`}
              type="time"
              step={3600}
              value={hhmm(v.weekly.hour ?? 14)}
              onChange={(e) => {
                if (e.target.value)
                  set({ weekly: { ...v.weekly, hour: Number(e.target.value.split(':')[0]) } });
              }}
            />
          </Field>
        </fieldset>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Time zone" id={`${id}-tz`}>
            <Select id={`${id}-tz`} value={v.timezone} onChange={(e) => set({ timezone: e.target.value })}>
              {timezones(v.timezone ?? 'UTC').map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Stale after (days without an update)" id={`${id}-stale`}>
            <Input
              id={`${id}-stale`}
              type="number"
              min={1}
              max={60}
              className="w-24"
              value={v.stale_days}
              onChange={(e) => set({ stale_days: Number(e.target.value) })}
            />
          </Field>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={v.suggestions}
            onChange={(e) => set({ suggestions: e.target.checked })}
          />
          Suggest follow-ups, new dates and owners with each digest (people approve them first)
        </label>
        {status.trusted_allowed.includes('comment') ? (
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex items-center gap-2 self-center text-sm">
              <input
                type="checkbox"
                checked={v.trusted.includes('comment')}
                disabled={!v.suggestions}
                onChange={(e) => set({ trusted: e.target.checked ? ['comment'] : [] })}
              />
              Post follow-up comments without approval (editors can undo for 7 days)
            </label>
            <Field label="At most per day" id={`${id}-cap`}>
              <Input
                id={`${id}-cap`}
                type="number"
                min={1}
                max={50}
                className="w-20"
                disabled={!v.trusted.includes('comment')}
                value={v.auto_daily_cap}
                onChange={(e) => set({ auto_daily_cap: Number(e.target.value) })}
              />
            </Field>
          </div>
        ) : (
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Everything waits for approval. An organization admin can let projects have follow-ups posted
            automatically (Admin › AI).
          </p>
        )}
        <fieldset className="flex flex-wrap items-end gap-3">
          <legend className="mb-1 text-sm font-semibold">Deliver by</legend>
          <label className="flex items-center gap-2 self-center text-sm">
            <input
              type="checkbox"
              checked={v.delivery.in_app}
              onChange={(e) => set({ delivery: { ...v.delivery, in_app: e.target.checked } })}
            />
            Notification (and phone, where turned on)
          </label>
          <label className="flex items-center gap-2 self-center text-sm">
            <input
              type="checkbox"
              checked={v.delivery.email}
              disabled={!status.email_available && !v.delivery.email}
              onChange={(e) => set({ delivery: { ...v.delivery, email: e.target.checked } })}
            />
            Email{status.email_available ? '' : ' (not set up on this server)'}
          </label>
          <Field label="Slack or Teams (digest only)" id={`${id}-ch`}>
            <Select
              id={`${id}-ch`}
              value={v.delivery.channel_id ?? ''}
              onChange={(e) => set({ delivery: { ...v.delivery, channel_id: e.target.value || null } })}
            >
              <option value="">None</option>
              {channels.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.kind === 'teams' ? 'Teams' : 'Slack'})
                </option>
              ))}
            </Select>
          </Field>
        </fieldset>
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={save.isPending}>
            {saved ? 'Save' : 'Turn on'}
          </Button>
          {saved?.enabled && (
            <>
              <GhostButton
                type="button"
                disabled={run.isPending}
                aria-busy={run.isPending && run.variables === 'digest'}
                onClick={() => run.mutate('digest')}
              >
                {run.isPending && run.variables === 'digest' ? 'Writing…' : 'Write a digest now'}
              </GhostButton>
              <GhostButton
                type="button"
                disabled={run.isPending}
                aria-busy={run.isPending && run.variables === 'weekly'}
                onClick={() => run.mutate('weekly')}
              >
                {run.isPending && run.variables === 'weekly' ? 'Writing…' : 'Write a weekly draft now'}
              </GhostButton>
            </>
          )}
          {saved && (
            <GhostButton
              type="button"
              disabled={remove.isPending}
              onClick={async () =>
                (await confirm({
                  title: 'Remove the project assistant?',
                  body: 'It stops writing digests and leaves the project. Digests already written stay here.',
                  confirmLabel: 'Remove',
                  danger: true,
                })) && remove.mutate()
              }
            >
              Remove
            </GhostButton>
          )}
        </div>
        <ErrorText error={save.error ?? run.error ?? remove.error} />
      </form>
    </section>
  );
}
