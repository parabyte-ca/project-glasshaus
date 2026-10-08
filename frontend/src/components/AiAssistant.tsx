import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useId, useState, type FormEvent } from 'react';
import { Link } from 'react-router';

import { api, unwrap, type ProjectDetail, type Schemas } from '../api/client';
import { Markdown } from './Markdown';
import { Button, ErrorText, Field, GhostButton } from './ui';

type Feature = Schemas['AiStatus']['features'][number];
type Draft = Schemas['DraftTask'];

const TABS: [Feature, string][] = [
  ['summaries', 'Status update'],
  ['drafting', 'Draft tasks'],
  ['risks', 'Risks'],
];

function Notice() {
  return (
    <p className="text-xs text-slate-600 dark:text-slate-400">
      Written by AI from this project’s data. Check it before you rely on it or share it.
    </p>
  );
}

/** Project assistant: AI status updates, task drafts and risk flags. Read-only until you add drafts. */
export function AiAssistant({ project, features }: { project: ProjectDetail; features: Feature[] }) {
  const tabs = TABS.filter(([key]) => features.includes(key));
  const [tab, setTab] = useState<Feature>(tabs[0]?.[0] ?? 'summaries');
  const base = useId();
  if (tabs.length === 0) return null;
  return (
    <section
      aria-labelledby={`${base}-h`}
      className="flex flex-col gap-3 rounded-lg border border-slate-200 p-4 dark:border-slate-700"
    >
      <h2 id={`${base}-h`} className="text-lg font-semibold">
        Assistant
      </h2>
      <div role="tablist" aria-label="Assistant tools" className="flex flex-wrap gap-1">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            id={`${base}-tab-${key}`}
            type="button"
            role="tab"
            aria-selected={tab === key}
            aria-controls={`${base}-panel`}
            onClick={() => setTab(key)}
            className={`rounded-md px-3 py-1.5 text-sm focus-visible:outline-2 focus-visible:outline-sky-600 ${tab === key ? 'bg-sky-700 text-white' : 'hover:bg-slate-100 dark:hover:bg-slate-800'}`}
          >
            {label}
          </button>
        ))}
      </div>
      <div id={`${base}-panel`} role="tabpanel" aria-labelledby={`${base}-tab-${tab}`}>
        {tab === 'summaries' && <StatusUpdate project={project} />}
        {tab === 'drafting' && <DraftTasks project={project} />}
        {tab === 'risks' && <Risks project={project} />}
      </div>
    </section>
  );
}

function StatusUpdate({ project }: { project: ProjectDetail }) {
  const [days, setDays] = useState(7);
  const [copied, setCopied] = useState(false);
  const run = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/ai/projects/{project_id}/status-report', {
          params: { path: { project_id: project.id }, query: { days } },
        }),
      ),
  });
  const r = run.data?.report;
  const text = r
    ? [
        r.headline,
        '',
        r.summary,
        '',
        ...r.highlights.map((h) => `- ${h}`),
        ...r.concerns.map((c) => `- ⚠ ${c}`),
      ].join('\n')
    : '';
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Period" id="ai-days">
          <select
            id="ai-days"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-900"
          >
            <option value={7}>Last 7 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
          </select>
        </Field>
        <Button onClick={() => run.mutate()} disabled={run.isPending}>
          {run.isPending ? 'Writing…' : r ? 'Write again' : 'Write status update'}
        </Button>
      </div>
      <ErrorText error={run.error} />
      {r && (
        <article aria-live="polite" className="flex flex-col gap-2">
          <h3 className="font-semibold">{r.headline}</h3>
          <Markdown text={r.summary} />
          {r.highlights.length > 0 && (
            <>
              <h4 className="text-sm font-semibold">Highlights</h4>
              <ul className="list-disc pl-5 text-sm">
                {r.highlights.map((h, i) => (
                  <li key={i}>{h}</li>
                ))}
              </ul>
            </>
          )}
          {r.concerns.length > 0 && (
            <>
              <h4 className="text-sm font-semibold">Concerns</h4>
              <ul className="list-disc pl-5 text-sm">
                {r.concerns.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </>
          )}
          <div className="flex items-center gap-3">
            <GhostButton
              onClick={() => {
                void navigator.clipboard?.writeText(text).then(() => setCopied(true));
              }}
            >
              Copy as text
            </GhostButton>
            {copied && (
              <span role="status" className="text-sm">
                Copied
              </span>
            )}
          </div>
          <Notice />
        </article>
      )}
    </div>
  );
}

function DraftTasks({ project }: { project: ProjectDetail }) {
  const queryClient = useQueryClient();
  const [brief, setBrief] = useState('');
  const [added, setAdded] = useState<Set<number>>(new Set());
  const run = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/ai/projects/{project_id}/draft-tasks', {
          params: { path: { project_id: project.id } },
          body: { brief, max_tasks: 8 },
        }),
      ),
    onSuccess: () => setAdded(new Set()),
  });
  const add = useMutation({
    mutationFn: async (items: [number, Draft][]) => {
      for (const [, d] of items) {
        await unwrap(
          api.POST('/api/v1/tasks', {
            body: {
              project_id: project.id,
              title: d.title,
              description: d.description,
              priority: d.priority,
              estimate_minutes: d.estimate_minutes,
              tags: d.tags,
            },
          }),
        );
      }
      return items.map(([i]) => i);
    },
    onSuccess: async (indexes) => {
      setAdded((prev) => new Set([...prev, ...indexes]));
      await queryClient.invalidateQueries({ queryKey: ['tasks', project.id] });
    },
  });
  const drafts = run.data?.drafts ?? [];
  const pending = drafts.map((d, i) => [i, d] as [number, Draft]).filter(([i]) => !added.has(i));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (brief.trim().length >= 3) run.mutate();
  };
  return (
    <div className="flex flex-col gap-3">
      <form onSubmit={submit} className="flex flex-col gap-2">
        <label htmlFor="ai-brief" className="text-sm font-medium">
          What needs doing?
        </label>
        <textarea
          id="ai-brief"
          rows={3}
          maxLength={4000}
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
          placeholder="Move the marketing site to the new hosting provider before the spring launch"
          className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-900"
        />
        <div>
          <Button type="submit" disabled={run.isPending || brief.trim().length < 3}>
            {run.isPending ? 'Drafting…' : 'Draft tasks'}
          </Button>
        </div>
      </form>
      <ErrorText error={run.error ?? add.error} />
      {drafts.length > 0 && (
        <div aria-live="polite" className="flex flex-col gap-2">
          <ul className="divide-y divide-slate-200 dark:divide-slate-700">
            {drafts.map((d, i) => (
              <li key={i} className="flex items-start justify-between gap-3 py-2 text-sm">
                <span>
                  <span className="font-medium">{d.title}</span>
                  <span className="block text-slate-600 dark:text-slate-400">
                    {d.priority !== 'none' && `${d.priority} priority · `}
                    {d.estimate_minutes ? `~${Math.round(d.estimate_minutes / 6) / 10} h` : 'no estimate'}
                    {d.tags.length > 0 && ` · ${d.tags.join(', ')}`}
                  </span>
                  {d.description && <span className="block whitespace-pre-line">{d.description}</span>}
                </span>
                {added.has(i) ? (
                  <span className="shrink-0 text-emerald-700 dark:text-emerald-400">Added</span>
                ) : (
                  <GhostButton
                    className="shrink-0"
                    aria-label={`Add task: ${d.title}`}
                    disabled={add.isPending}
                    onClick={() => add.mutate([[i, d]])}
                  >
                    Add
                  </GhostButton>
                )}
              </li>
            ))}
          </ul>
          {pending.length > 1 && (
            <div>
              <Button onClick={() => add.mutate(pending)} disabled={add.isPending}>
                Add all {pending.length}
              </Button>
            </div>
          )}
          <Notice />
        </div>
      )}
    </div>
  );
}

const SEVERITY = {
  high: 'border-red-600 text-red-800 dark:text-red-300',
  medium: 'border-amber-500 text-amber-800 dark:text-amber-300',
  low: 'border-slate-400 text-slate-700 dark:text-slate-300',
} as const;

function Risks({ project }: { project: ProjectDetail }) {
  const run = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/ai/projects/{project_id}/risks', { params: { path: { project_id: project.id } } }),
      ),
  });
  const risks = run.data?.risks;
  return (
    <div className="flex flex-col gap-3">
      <div>
        <Button onClick={() => run.mutate()} disabled={run.isPending}>
          {run.isPending ? 'Reviewing…' : risks ? 'Review again' : 'Review risks'}
        </Button>
      </div>
      <ErrorText error={run.error} />
      {risks && (
        <div aria-live="polite" className="flex flex-col gap-2">
          {risks.length === 0 && <p className="text-sm">No notable risks found.</p>}
          <ul className="flex flex-col gap-2">
            {risks.map((r, i) => (
              <li
                key={i}
                className={`rounded border-l-4 bg-slate-50 p-3 text-sm dark:bg-slate-900 ${SEVERITY[r.severity]}`}
              >
                <p className="font-semibold">
                  <span className="uppercase">{r.severity}</span>: {r.title}
                  {r.task_key && (
                    <>
                      {' · '}
                      <Link className="underline" to={`/projects/${project.key}?task=${r.task_key}`}>
                        {r.task_key}
                      </Link>
                    </>
                  )}
                </p>
                <p className="text-slate-800 dark:text-slate-200">{r.reason}</p>
                <p className="text-slate-800 dark:text-slate-200">
                  <span className="font-medium">Next step:</span> {r.suggestion}
                </p>
              </li>
            ))}
          </ul>
          <Notice />
        </div>
      )}
    </div>
  );
}
