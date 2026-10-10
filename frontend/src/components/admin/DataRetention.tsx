import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api, unwrap, type Schemas } from '../../api/client';
import { Button, ErrorText, Field, Input } from '../ui';
import { Section } from './common';

type Settings = Schemas['OrgSettingsRead'];
type RetentionKey = Exclude<keyof Settings, 'ai_enabled' | 'ai_features'>;
const FIELDS: [RetentionKey, string][] = [
  ['audit_retention_days', 'Audit log'],
  ['activity_retention_days', 'Activity history'],
  ['notification_retention_days', 'Notifications'],
  ['deleted_task_retention_days', 'Deleted tasks (restorable until purged)'],
];

export function DataRetention() {
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: ['org-settings'],
    queryFn: () => unwrap(api.GET('/api/v1/admin/settings')),
  });
  const [edits, setDraft] = useState<Settings | null>(null);
  const draft = edits ?? settings.data ?? null;
  const save = useMutation({
    mutationFn: (body: Schemas['OrgSettingsUpdate']) => unwrap(api.PATCH('/api/v1/admin/settings', { body })),
    onSuccess: (data) => queryClient.setQueryData(['org-settings'], data),
  });
  return (
    <div className="flex flex-col gap-8">
      <Section
        title="Retention"
        intro="Days to keep each kind of record; 0 keeps it forever. Older records are deleted nightly. The audit log keeps at least 30 days, and its own record of each clean-up. Deleted tasks with logged time are kept so time reports stay correct. Ended sign-in sessions (with their IP address) are deleted after 90 days."
      >
        {draft && (
          <form
            className="grid max-w-xl gap-3 sm:grid-cols-2"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate(Object.fromEntries(FIELDS.map(([key]) => [key, draft[key]])));
            }}
          >
            {FIELDS.map(([key, label]) => (
              <Field key={key} label={`${label} (days)`} id={`ret-${key}`}>
                <Input
                  id={`ret-${key}`}
                  type="number"
                  min={0}
                  max={3650}
                  value={draft[key]}
                  onChange={(e) => setDraft({ ...draft, [key]: Number(e.target.value) })}
                />
              </Field>
            ))}
            <div className="sm:col-span-2">
              <Button type="submit" disabled={save.isPending}>
                Save retention
              </Button>
              {save.isSuccess && (
                <span role="status" className="ml-3 text-sm text-emerald-700 dark:text-emerald-400">
                  Saved
                </span>
              )}
            </div>
          </form>
        )}
        <ErrorText error={settings.error ?? save.error} />
      </Section>
      <Section
        title="Export"
        intro="Download everything in this organization as a zip of JSON Lines files (one per table). Passwords, token hashes and other secrets are left out. The export is recorded in the audit log."
      >
        <a
          href="/api/v1/admin/export"
          className="self-start rounded-md bg-sky-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-800"
          download
        >
          Download export
        </a>
      </Section>
    </div>
  );
}
