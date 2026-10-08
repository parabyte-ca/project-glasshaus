import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { api, unwrap } from '../../api/client';
import { Field, GhostButton, Input, Select } from '../ui';
import { Section } from './common';
import { dateTime, table, td, th } from './format';

const PAGE = 100;

export function AuditLog() {
  const [action, setAction] = useState('');
  const [outcome, setOutcome] = useState('');
  const users = useQuery({
    queryKey: ['users', 'all'],
    queryFn: () => unwrap(api.GET('/api/v1/users', { params: { query: { limit: 500 } } })),
  });
  const names = new Map((users.data ?? []).map((u) => [u.id, u.name]));
  const log = useInfiniteQuery({
    queryKey: ['audit', action, outcome],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET('/api/v1/audit-log', {
          params: {
            query: {
              action: action || undefined,
              outcome: outcome || undefined,
              before: pageParam,
              limit: PAGE,
            },
          },
        }),
      ),
    getNextPageParam: (last) => (last.length === PAGE ? last[last.length - 1]?.created_at : undefined),
  });
  const rows = log.data?.pages.flat() ?? [];
  return (
    <Section
      title="Audit log"
      intro="Every change, sign-in, single sign-on, provisioning and MCP tool call, with who did it and from which client. Retention is set under Data & retention."
    >
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Action starts with" id="audit-action">
          <Input
            id="audit-action"
            value={action}
            onChange={(e) => setAction(e.target.value)}
            placeholder="auth."
          />
        </Field>
        <Field label="Outcome" id="audit-outcome">
          <Select id="audit-outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            <option value="">Any</option>
            <option value="ok">ok</option>
            <option value="denied">denied</option>
            <option value="error">error</option>
            <option value="rate_limited">rate limited</option>
          </Select>
        </Field>
      </div>
      <div className="overflow-x-auto">
        <table className={table}>
          <thead>
            <tr>
              <th className={th}>When</th>
              <th className={th}>Action</th>
              <th className={th}>Who</th>
              <th className={th}>Client</th>
              <th className={th}>Target</th>
              <th className={th}>Outcome</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.id}>
                <td className={`${td} whitespace-nowrap`}>{dateTime(e.created_at)}</td>
                <td className={`${td} font-mono text-xs`}>{e.action}</td>
                <td className={td}>
                  {e.actor_id ? (names.get(e.actor_id) ?? e.actor_id.slice(0, 8)) : e.actor_method}
                </td>
                <td className={`${td} text-xs`}>{e.client ?? e.actor_method}</td>
                <td className={`${td} font-mono text-xs`}>{e.target ?? ''}</td>
                <td className={td}>{e.outcome}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {log.hasNextPage && (
        <GhostButton
          onClick={() => log.fetchNextPage()}
          disabled={log.isFetchingNextPage}
          className="self-start"
        >
          Load more
        </GhostButton>
      )}
    </Section>
  );
}
