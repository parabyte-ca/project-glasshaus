import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, unwrap, type Schemas } from '../../api/client';
import { toast } from '../../lib/toast';
import { Button, ErrorText } from '../ui';
import { Section } from './common';

type Feature = Schemas['OrgSettingsRead']['ai_features'][number];
const AI_FEATURES: [Feature, string, string][] = [
  ['summaries', 'Status updates', 'Write a status update from a project’s status summary.'],
  ['drafting', 'Task drafting', 'Propose tasks from a short brief; people choose which to add.'],
  ['risks', 'Risk flags', 'Point out late, overloaded or vague work with a suggested next step.'],
  [
    'search',
    'Ask in plain words',
    'Turn a question into task filters (only the question, project keys and names are sent).',
  ],
  [
    'reports',
    'Questions about reports',
    'Answer a question from a report run with the asker’s access. The question, project keys, people’s names and saved report names are sent, then the report table (group names such as projects, people and tags, and the numbers); never task titles or descriptions.',
  ],
  [
    'assistant',
    'Project assistant',
    'Add a short AI summary and focus list to the daily stand-up digest, and write the weekly status draft, for projects that turn the assistant on. Sends the open, due, overdue, stale and recently done tasks (keys, titles, statuses, due dates, owners’ names). Without this, digests list the facts only.',
  ],
];

/** Organization switch and per-feature settings for the optional AI assistant. */
export function AiSettings() {
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ['ai-status'], queryFn: () => unwrap(api.GET('/api/v1/ai/status')) });
  const settings = useQuery({
    queryKey: ['org-settings'],
    queryFn: () => unwrap(api.GET('/api/v1/admin/settings')),
  });
  const save = useMutation({
    mutationFn: (body: Schemas['OrgSettingsUpdate']) => unwrap(api.PATCH('/api/v1/admin/settings', { body })),
    onSuccess: async (data) => {
      queryClient.setQueryData(['org-settings'], data);
      toast('AI settings saved.');
      await queryClient.invalidateQueries({ queryKey: ['ai-status'] });
    },
  });
  const s = settings.data;
  const available = status.data?.available ?? false;
  return (
    <Section
      title="AI"
      intro={
        <>
          Optional help with status updates, task drafting, risk flags, plain-language search and questions
          about reports. It only reads: drafts and suggestions change nothing until someone applies them.
          Project data is sent to the configured model provider, every request is recorded in the audit log
          (without the content), and people are limited to a few requests a minute.
        </>
      }
    >
      {status.data && !available && (
        <p
          role="note"
          className="max-w-3xl rounded border border-slate-300 p-3 text-sm dark:border-slate-600"
        >
          No AI provider is configured on this server. Set <code>GLASSHAUS_AI_PROVIDER</code> (Claude, or a
          local model through an OpenAI-compatible server such as Ollama) and restart; see docs/ai.md.
        </p>
      )}
      {status.data && available && (
        <p className="text-sm">
          Provider: <strong>{status.data.provider}</strong> · model <code>{status.data.model}</code>
        </p>
      )}
      {s && (
        <form
          className="flex max-w-3xl flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            const form = new FormData(e.currentTarget);
            save.mutate({
              // Without a provider those boxes are disabled (and missing from the form): keep what is saved.
              ...(available
                ? {
                    ai_enabled: form.get('ai_enabled') === 'on',
                    ai_features: AI_FEATURES.map(([key]) => key).filter(
                      (key) => form.get(`f-${key}`) === 'on',
                    ),
                  }
                : {}),
              assistant_trusted: form.get('trust-comment') === 'on' ? ['comment'] : [],
            });
          }}
        >
          <label className="flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" name="ai_enabled" defaultChecked={s.ai_enabled} disabled={!available} />
            Turn on the AI assistant for this organization
          </label>
          <fieldset className="flex flex-col gap-2 rounded border border-slate-200 p-3 dark:border-slate-700">
            <legend className="px-1 text-sm font-medium">Features</legend>
            {AI_FEATURES.map(([key, label, help]) => (
              <div key={key} className="flex items-start gap-2 text-sm">
                <input
                  id={`ai-f-${key}`}
                  type="checkbox"
                  name={`f-${key}`}
                  className="mt-1"
                  defaultChecked={s.ai_features.includes(key)}
                  disabled={!available}
                />
                <label htmlFor={`ai-f-${key}`}>
                  <span className="font-medium">{label}</span>
                  <span className="block text-slate-600 dark:text-slate-400">{help}</span>
                </label>
              </div>
            ))}
          </fieldset>
          <fieldset className="flex flex-col gap-2 rounded border border-slate-200 p-3 dark:border-slate-700">
            <legend className="px-1 text-sm font-medium">
              What the project assistant may do without approval
            </legend>
            <div className="flex items-start gap-2 text-sm">
              <input
                id="ai-trust-comment"
                type="checkbox"
                name="trust-comment"
                className="mt-1"
                defaultChecked={s.assistant_trusted.includes('comment')}
              />
              <label htmlFor="ai-trust-comment">
                <span className="font-medium">Post follow-up comments</span>
                <span className="block text-slate-600 dark:text-slate-400">
                  Projects may then let the assistant post its follow-ups on overdue and stale work by itself,
                  up to a daily limit they set. The task’s owner is mentioned, and project editors can undo a
                  follow-up for 7 days. Everything else still waits for approval.
                </span>
              </label>
            </div>
          </fieldset>
          <div>
            <Button type="submit" disabled={save.isPending}>
              Save AI settings
            </Button>
          </div>
        </form>
      )}
      <ErrorText error={status.error ?? settings.error ?? save.error} />
    </Section>
  );
}
