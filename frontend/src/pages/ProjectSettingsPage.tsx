import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router';

import { api, unwrap, type CustomField } from '../api/client';
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

export function ProjectSettingsPage() {
  const { projectKey = '' } = useParams();
  const queryClient = useQueryClient();
  const { project, fields } = useProject(projectKey);
  const [name, setName] = useState('');
  const [type, setType] = useState<CustomField['type']>('text');
  const [options, setOptions] = useState('');
  const projectId = project.data?.id;
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['fields', projectId] });

  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/projects/{project_id}/fields', {
          params: { path: { project_id: projectId! } },
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
          params: { path: { project_id: projectId!, field_id: fieldId } },
        }),
      ),
    onSettled: () => void refresh(),
  });

  if (!project.data) return <p role="status">Loading…</p>;
  const needsOptions = type === 'select' || type === 'multi_select';
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <div>
        <Link
          to={`/projects/${projectKey}`}
          className="text-sm text-sky-700 hover:underline dark:text-sky-400"
        >
          ← {project.data.name}
        </Link>
        <h1 className="text-2xl font-bold">Project settings</h1>
      </div>
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
