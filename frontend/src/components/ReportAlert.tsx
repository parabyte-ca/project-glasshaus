import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useId, useState } from 'react';

import { api, unwrap, type SavedReport, type ScheduleSpec } from '../api/client';
import { useConfirm } from '../lib/confirm';
import { MEASURES, type Source } from '../lib/reportMeta';
import { toast } from '../lib/toast';
import { ScheduleFields } from './AutomationRules';
import { Button, ErrorText, Field, GhostButton, Input, Select } from './ui';

type Direction = 'above' | 'below';

const defaultSchedule = (): ScheduleSpec => ({
  frequency: 'daily',
  weekday: null,
  day: null,
  hour: 8,
  minute: 0,
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
});

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });

/**
 * Tell me when this report's total goes above or below a number. Checked on a schedule with your
 * access; you are told when it goes off and again when it is back, not on every check.
 */
export function ReportAlert({ report, emailAvailable }: { report: SavedReport; emailAvailable: boolean }) {
  const id = useId();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const key = ['report-alert', report.id];
  const path = { params: { path: { report_id: report.id } } };
  const alert = useQuery({
    queryKey: key,
    queryFn: () => unwrap(api.GET('/api/v1/reports/{report_id}/alert', path)),
  });
  const source = (report.definition.source ?? 'tasks') as Source;
  const labels = new Map<string, string>(MEASURES[source]);
  const measures = (report.definition.measures ?? []).map((m) => [m, labels.get(m) ?? m] as const);
  const a = alert.data ?? null;

  const [draft, setDraft] = useState<{
    measure?: string;
    direction?: Direction;
    threshold?: string;
    schedule?: ScheduleSpec;
    email?: boolean;
  }>({});
  const measure = draft.measure ?? a?.measure ?? measures[0]?.[0] ?? 'count';
  const direction = draft.direction ?? (a?.direction as Direction | undefined) ?? 'above';
  const threshold = draft.threshold ?? (a ? String(a.threshold) : '');
  const schedule = draft.schedule ?? (a?.schedule as ScheduleSpec | undefined) ?? defaultSchedule();
  const email = draft.email ?? a?.email ?? false;
  const done = async () => {
    setDraft({});
    await queryClient.invalidateQueries({ queryKey: key });
  };

  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.PUT('/api/v1/reports/{report_id}/alert', {
          ...path,
          body: { measure, direction, threshold: Number(threshold), schedule, email },
        }),
      ),
    onSuccess: async (data) => {
      toast(`Alert saved. First check: ${when(data.next_run_at)}`);
      await done();
    },
  });
  const remove = useMutation({
    mutationFn: () => unwrap(api.DELETE('/api/v1/reports/{report_id}/alert', path)),
    onSuccess: async () => {
      toast('Alert removed');
      await done();
    },
  });
  const check = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/reports/{report_id}/alert/check', path)),
    onSuccess: (data) => {
      queryClient.setQueryData(key, data);
      toast(
        data.state === 'triggered'
          ? `${data.measure_label} is ${data.last_value}: past your alert`
          : `${data.measure_label} is ${data.last_value ?? 'not available'}`,
      );
    },
  });

  if (alert.isPending) return null;
  const valid = threshold.trim() !== '' && Number.isFinite(Number(threshold));
  return (
    <section aria-labelledby={`${id}-h`} className="flex max-w-5xl flex-col gap-3">
      <h2 id={`${id}-h`} className="text-lg font-semibold">
        Alert me
      </h2>
      <ErrorText error={alert.error} />
      <p className="text-sm text-slate-600 dark:text-slate-400">
        {a
          ? a.state === 'triggered'
            ? `Alert is on: ${a.measure_label} was ${a.last_value} when checked ${a.last_checked_at ? when(a.last_checked_at) : ''}.`
            : `Watching ${a.measure_label}${a.last_value !== null ? ` (now ${a.last_value})` : ''}. Next check ${when(a.next_run_at)}.`
          : 'Get a notification when a total on this report goes above or below a number, and again when it is back.'}
      </p>
      {a?.state === 'triggered' && (
        <p className="flex items-center gap-1 text-sm font-medium text-red-700 dark:text-red-400">
          <span aria-hidden="true">!</span> {a.measure_label} is {direction} {a.threshold}
        </p>
      )}
      {a?.last_error && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-400">
          The last check could not run: {a.last_error}
        </p>
      )}
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) save.mutate();
        }}
      >
        <Field label="When" id={`${id}-measure`}>
          <Select
            id={`${id}-measure`}
            value={measure}
            onChange={(e) => setDraft({ ...draft, measure: e.target.value })}
          >
            {measures.map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Goes" id={`${id}-direction`}>
          <Select
            id={`${id}-direction`}
            value={direction}
            onChange={(e) => setDraft({ ...draft, direction: e.target.value as Direction })}
          >
            <option value="above">above</option>
            <option value="below">below</option>
          </Select>
        </Field>
        <Field label="Number" id={`${id}-threshold`}>
          <Input
            id={`${id}-threshold`}
            type="number"
            step="any"
            className="w-28"
            required
            value={threshold}
            onChange={(e) => setDraft({ ...draft, threshold: e.target.value })}
          />
        </Field>
        <ScheduleFields
          value={schedule}
          onChange={(patch) => setDraft({ ...draft, schedule: { ...schedule, ...patch } })}
          idPrefix={`${id}-s`}
        />
        {emailAvailable && (
          <label className="flex items-center gap-2 self-center text-sm">
            <input
              type="checkbox"
              checked={email}
              onChange={(e) => setDraft({ ...draft, email: e.target.checked })}
            />
            Also email me
          </label>
        )}
        <Button type="submit" disabled={save.isPending || !valid}>
          {a ? 'Update alert' : 'Create alert'}
        </Button>
        {a && (
          <>
            <GhostButton type="button" onClick={() => check.mutate()} disabled={check.isPending}>
              {check.isPending ? 'Checking…' : 'Check now'}
            </GhostButton>
            <GhostButton
              type="button"
              disabled={remove.isPending}
              onClick={async () =>
                (await confirm({
                  title: 'Remove this alert?',
                  body: 'You will no longer be told when this report crosses its threshold.',
                  confirmLabel: 'Remove alert',
                  danger: true,
                })) && remove.mutate()
              }
            >
              Remove alert
            </GhostButton>
          </>
        )}
      </form>
      <ErrorText error={save.error ?? remove.error ?? check.error} />
    </section>
  );
}
