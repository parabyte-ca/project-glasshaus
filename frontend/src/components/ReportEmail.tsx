import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useId, useState } from 'react';

import { api, unwrap, type ScheduleSpec } from '../api/client';
import { toast } from '../lib/toast';
import { ScheduleFields } from './AutomationRules';
import { Button, ErrorText, GhostButton } from './ui';

const defaultSchedule = (): ScheduleSpec => ({
  frequency: 'weekly',
  weekday: 0,
  day: null,
  hour: 8,
  minute: 0,
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
});

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });

/** Email this saved report to yourself on a schedule; each send uses your access at that time. */
export function ReportEmail({ reportId }: { reportId: string }) {
  const id = useId();
  const queryClient = useQueryClient();
  const key = ['report-email', reportId];
  const status = useQuery({
    queryKey: key,
    queryFn: () =>
      unwrap(api.GET('/api/v1/reports/{report_id}/email', { params: { path: { report_id: reportId } } })),
  });
  const sub = status.data?.subscription ?? null;
  const [schedule, setSchedule] = useState<ScheduleSpec | null>(null);
  const [attachCsv, setAttachCsv] = useState<boolean | null>(null);
  const current = schedule ?? (sub?.schedule as ScheduleSpec | undefined) ?? defaultSchedule();
  const csv = attachCsv ?? sub?.attach_csv ?? true;
  const path = { params: { path: { report_id: reportId } } };
  const done = async () => {
    setSchedule(null);
    setAttachCsv(null);
    await queryClient.invalidateQueries({ queryKey: key });
  };
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.PUT('/api/v1/reports/{report_id}/email', {
          ...path,
          body: { schedule: current, attach_csv: csv },
        }),
      ),
    onSuccess: async (data) => {
      toast(`Report email saved. Next one: ${when(data.next_run_at)}`);
      await done();
    },
  });
  const stop = useMutation({
    mutationFn: () => unwrap(api.DELETE('/api/v1/reports/{report_id}/email', path)),
    onSuccess: async () => {
      toast('Report emails stopped');
      await done();
    },
  });
  const sendNow = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/reports/{report_id}/email/send', {
          params: { path: { report_id: reportId }, query: { attach_csv: csv } },
        }),
      ),
    onSuccess: (data) => toast(`Sent to ${data.sent_to}`),
  });

  if (!status.data) return <ErrorText error={status.error} />;
  return (
    <section aria-labelledby={`${id}-h`} className="flex max-w-5xl flex-col gap-3">
      <h2 id={`${id}-h`} className="text-lg font-semibold">
        Email me this report
      </h2>
      {!status.data.available ? (
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Email isn’t set up on this server yet. An administrator can add an SMTP server
          (GLASSHAUS_SMTP_HOST); see the reports guide.
        </p>
      ) : (
        <>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            {sub
              ? `Next email ${when(sub.next_run_at)}${sub.last_sent_at ? `; last sent ${when(sub.last_sent_at)}` : ''}.`
              : 'Get this report by email. Each email is run with your access at the time it is sent.'}
          </p>
          {sub?.last_error && (
            <p role="alert" className="text-sm text-red-700 dark:text-red-400">
              The last email could not be sent: {sub.last_error}
            </p>
          )}
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            <ScheduleFields
              value={current}
              onChange={(patch) => setSchedule({ ...current, ...patch })}
              idPrefix={`${id}-s`}
            />
            <label className="flex items-center gap-2 self-center text-sm">
              <input type="checkbox" checked={csv} onChange={(e) => setAttachCsv(e.target.checked)} />
              Attach CSV
            </label>
            <Button type="submit" disabled={save.isPending}>
              {sub ? 'Update schedule' : 'Start emails'}
            </Button>
            {sub && (
              <GhostButton type="button" onClick={() => stop.mutate()} disabled={stop.isPending}>
                Stop emails
              </GhostButton>
            )}
            <GhostButton type="button" onClick={() => sendNow.mutate()} disabled={sendNow.isPending}>
              {sendNow.isPending ? 'Sending…' : 'Email me now'}
            </GhostButton>
          </form>
          <ErrorText error={save.error ?? stop.error ?? sendNow.error} />
        </>
      )}
    </section>
  );
}
