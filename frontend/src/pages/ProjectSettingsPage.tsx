import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';

import { api, unwrap, type CustomField } from '../api/client';
import { AutomationRules } from '../components/AutomationRules';
import { RecurringTasks, SaveAsTemplate } from '../components/RecurringTasks';
import { Button, ErrorText, Field, GhostButton, Input, Select } from '../components/ui';
import { useProject } from '../lib/useProject';

const TYPES: { value: CustomField['type']; label: string }[] = [
  { value: 'text', label: 'Text' },
  { value: 'number', label: 'Number' },
  { value: 'date', label: 'Date' },
  { value: 'select', label: 'Single select' },
  { value: 'multi_select', label: 'Multi select' },
  { value: 'user', label: 'Person' },
  { value: 'checkbox', label: 'Checkbox' },
  { value: 'url', label: 'URL' },
];

const TABS = [
  { id: 'fields', label: 'Custom fields' },
  { id: 'automations', label: 'Automations' },
  { id: 'recurring', label: 'Recurring tasks' },
  { id: 'template', label: 'Template' },
] as const;
type Tab = (typeof TABS)[number]['id'];

export function ProjectSettingsPage() {
  const { projectKey = '' } = useParams();
  const { project, fields, users } = useProject(projectKey);
  const [params, setParams] = useSearchParams();
  const tab: Tab = TABS.find((t) => t.id === params.get('tab'))?.id ?? 'fields';

  if (!project.data) return <p role="status">Loading…</p>;
  const p = project.data;
  return (
    <div className="flex max-w-5xl flex-col gap-6">
      <div>
        <Link
          to={`/projects/${projectKey}`}
          className="text-sm text-sky-700 hover:underline dark:text-sky-400"
        >
          ← {p.name}
        </Link>
        <h1 className="text-2xl font-bold">Project settings</h1>
      </div>
      <div
        role="tablist"
        aria-label="Settings sections"
        className="flex gap-1 border-b border-slate-200 dark:border-slate-800"
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            type="button"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`panel-${t.id}`}
            onClick={() => setParams(t.id === 'fields' ? {} : { tab: t.id }, { replace: true })}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${
              tab === t.id
                ? 'border-sky-700 font-medium text-sky-800 dark:border-sky-400 dark:text-sky-300'
                : 'border-transparent text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <section role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === 'fields' && <FieldsSettings projectId={p.id} fields={fields} />}
        {tab === 'automations' && <AutomationRules project={p} fields={fields} users={users} />}
        {tab === 'recurring' && <RecurringTasks projectId={p.id} users={users} />}
        {tab === 'template' && <SaveAsTemplate projectId={p.id} projectName={p.name} />}
      </section>
    </div>
  );
}

function FieldsSettings({ projectId, fields }: { projectId: string; fields: CustomField[] }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [type, setType] = useState<CustomField['type']>('text');
  const [options, setOptions] = useState('');
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['fields', projectId] });

  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/projects/{project_id}/fields', {
          params: { path: { project_id: projectId } },
          body: {
            name,
            type,
            options: options
              .split(',')
              .map((o) => o.trim())
              .filter(Boolean)
              .map((label) => ({ label })),
          },
        }),
      ),
    onSuccess: () => {
      setName('');
      setOptions('');
      void refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (fieldId: string) =>
      unwrap(
        api.DELETE('/api/v1/projects/{project_id}/fields/{field_id}', {
          params: { path: { project_id: projectId, field_id: fieldId } },
        }),
      ),
    onSettled: () => void refresh(),
  });

  const needsOptions = type === 'select' || type === 'multi_select';
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <section aria-labelledby="fields-h" className="flex flex-col gap-3">
        <h2 id="fields-h" className="text-lg font-semibold">
          Custom fields
        </h2>
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
          {fields.length === 0 && (
            <li className="p-3 text-sm text-slate-600 dark:text-slate-400">No custom fields yet.</li>
          )}
          {fields.map((f) => (
            <li key={f.id} className="flex items-center justify-between gap-3 p-3 text-sm">
              <span>
                <span className="font-medium">{f.name}</span>{' '}
                <span className="text-slate-600 dark:text-slate-400">
                  {TYPES.find((t) => t.value === f.type)?.label}
                  {f.options.length > 0 && `: ${f.options.map((o) => o.label).join(', ')}`}
                </span>
              </span>
              <GhostButton
                aria-label={`Delete field ${f.name}`}
                onClick={() =>
                  window.confirm(`Delete "${f.name}" and its values on every task?`) && remove.mutate(f.id)
                }
              >
                Delete
              </GhostButton>
            </li>
          ))}
        </ul>
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <Field label="Field name" id="f-name">
            <Input
              id="f-name"
              required
              maxLength={60}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label="Type" id="f-type">
            <Select id="f-type" value={type} onChange={(e) => setType(e.target.value as CustomField['type'])}>
              {TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </Select>
          </Field>
          {needsOptions && (
            <Field label="Options (comma separated)" id="f-options">
              <Input id="f-options" required value={options} onChange={(e) => setOptions(e.target.value)} />
            </Field>
          )}
          <Button type="submit" disabled={create.isPending}>
            Add field
          </Button>
        </form>
        <ErrorText error={create.error ?? remove.error} />
      </section>
    </div>
  );
}
