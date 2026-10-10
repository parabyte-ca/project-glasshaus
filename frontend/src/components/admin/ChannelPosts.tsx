import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useId, useState } from 'react';

import { api, type Schemas, type ScheduleSpec, unwrap } from '../../api/client';
import { useConfirm } from '../../lib/confirm';
import { ScheduleFields } from '../AutomationRules';
import { Button, ErrorText, Field, GhostButton, Select } from '../ui';
import { dateTime, table, td, th } from './format';

type Integration = Schemas['IntegrationRead'];
type Post = Schemas['ChannelPostRead'];

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

const describe = (s: Post['schedule']) => {
  const time = `${String(s.hour ?? 9).padStart(2, '0')}:${String(s.minute ?? 0).padStart(2, '0')}`;
  const day =
    s.frequency === 'weekly'
      ? `${WEEKDAYS[s.weekday ?? 0]}s`
      : s.frequency === 'monthly'
        ? `day ${s.day ?? 1} of each month`
        : 'every day';
  return `${day} at ${time} (${s.timezone ?? 'UTC'})`;
};

const defaultSchedule = (): ScheduleSpec => ({
  frequency: 'weekly',
  weekday: 0,
  day: null,
  hour: 9,
  minute: 0,
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
});

/**
 * Saved reports and project status, posted to this Slack or Teams channel on a schedule. Each post
 * runs with the access of the person who set it up; a project's channel only gets that project.
 */
export function ChannelPosts({ integration }: { integration: Integration }) {
  const id = useId();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const key = ['channel-posts', integration.id];
  const path = { params: { path: { integration_id: integration.id } } };
  const list = useQuery({
    queryKey: key,
    queryFn: () => unwrap(api.GET('/api/v1/integrations/{integration_id}/posts', path)),
  });
  const reports = useQuery({ queryKey: ['reports'], queryFn: () => unwrap(api.GET('/api/v1/reports')) });
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => unwrap(api.GET('/api/v1/projects')) });
  const [kind, setKind] = useState<'report' | 'status'>('report');
  const [reportId, setReportId] = useState('');
  const [projectId, setProjectId] = useState(integration.project_id ?? '');
  const [schedule, setSchedule] = useState<ScheduleSpec>(defaultSchedule);
  const refresh = () => queryClient.invalidateQueries({ queryKey: key });

  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/integrations/{integration_id}/posts', {
          ...path,
          body: {
            kind,
            report_id: kind === 'report' ? reportId : null,
            project_id: kind === 'status' ? projectId : null,
            schedule,
          },
        }),
      ),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (postId: string) =>
      unwrap(
        api.DELETE('/api/v1/integrations/{integration_id}/posts/{post_id}', {
          params: { path: { integration_id: integration.id, post_id: postId } },
        }),
      ),
    onSuccess: refresh,
  });
  const send = useMutation({
    mutationFn: (postId: string) =>
      unwrap(
        api.POST('/api/v1/integrations/{integration_id}/posts/{post_id}/send', {
          params: { path: { integration_id: integration.id, post_id: postId } },
        }),
      ),
    onSettled: async () => {
      await refresh();
      await queryClient.invalidateQueries({ queryKey: ['deliveries', integration.id] });
    },
  });

  const choices = (projects.data ?? []).filter(
    (p) => !integration.project_id || p.id === integration.project_id,
  );
  return (
    <section aria-labelledby={`${id}-h`} className="flex flex-col gap-3">
      <h3 id={`${id}-h`} className="font-semibold">
        Scheduled posts to {integration.name}
      </h3>
      <p className="text-sm text-slate-600 dark:text-slate-400">
        Each post uses the access of the person who set it up
        {integration.project_id ? ', and only this channel’s project' : ''}. Everyone in the channel sees it.
      </p>
      <ErrorText error={list.error} />
      {list.data?.length === 0 && (
        <p className="text-sm text-slate-600 dark:text-slate-400">No scheduled posts yet.</p>
      )}
      {(list.data?.length ?? 0) > 0 && (
        <table className={table}>
          <caption className="sr-only">Scheduled posts</caption>
          <thead>
            <tr>
              <th scope="col" className={th}>
                Post
              </th>
              <th scope="col" className={th}>
                When
              </th>
              <th scope="col" className={th}>
                Last sent
              </th>
              <th scope="col" className={th}>
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {(list.data ?? []).map((p) => (
              <tr key={p.id}>
                <td className={td}>
                  {p.kind === 'report' ? 'Report' : 'Status'}: {p.title}
                </td>
                <td className={td}>{describe(p.schedule)}</td>
                <td className={td}>
                  {p.last_error ? (
                    <span className="text-red-700 dark:text-red-400">Failed: {p.last_error}</span>
                  ) : (
                    dateTime(p.last_sent_at)
                  )}
                </td>
                <td className={`${td} whitespace-nowrap`}>
                  <GhostButton
                    aria-label={`Post ${p.title} now`}
                    onClick={() => send.mutate(p.id)}
                    disabled={send.isPending}
                  >
                    Post now
                  </GhostButton>
                  <GhostButton
                    aria-label={`Stop posting ${p.title}`}
                    onClick={async () =>
                      (await confirm({
                        title: `Stop posting ${p.title}?`,
                        body: 'The scheduled post is removed. Messages already posted stay in the channel.',
                        confirmLabel: 'Stop posting',
                        danger: true,
                      })) && remove.mutate(p.id)
                    }
                  >
                    Stop
                  </GhostButton>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {send.data && (
        <p role="status" className="text-sm">
          Post: {send.data.status}
          {send.data.error ? ` (${send.data.error})` : ''}
        </p>
      )}
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <Field label="Post" id={`${id}-kind`}>
          <Select
            id={`${id}-kind`}
            value={kind}
            onChange={(e) => setKind(e.target.value as 'report' | 'status')}
          >
            <option value="report">A saved report</option>
            <option value="status">A project’s status</option>
          </Select>
        </Field>
        {kind === 'report' ? (
          <Field label="Report" id={`${id}-report`}>
            <Select
              id={`${id}-report`}
              required
              value={reportId}
              onChange={(e) => setReportId(e.target.value)}
            >
              <option value="">Choose…</option>
              {(reports.data ?? []).map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </Select>
          </Field>
        ) : (
          <Field label="Project" id={`${id}-project`}>
            <Select
              id={`${id}-project`}
              required
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
            >
              <option value="">Choose…</option>
              {choices.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.key} {p.name}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <ScheduleFields
          value={schedule}
          onChange={(patch) => setSchedule({ ...schedule, ...patch })}
          idPrefix={`${id}-s`}
        />
        <Button type="submit" disabled={create.isPending}>
          Add post
        </Button>
      </form>
      <ErrorText error={create.error ?? remove.error ?? send.error} />
    </section>
  );
}
