import { useInfiniteQuery, useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { api, unwrap } from '../../api/client';
import { CopyButton, ErrorText, Field, GhostButton, Input, ScrollArea, Select } from '../ui';
import { Section } from './common';
import { dateTime, table, td, th } from './format';

const PAGE = 100;

/** Recomputes the hash chain on the server: shows whether any entry was changed, removed or inserted. */
function ChainCheck() {
  const check = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/audit-log/verify')),
  });
  const result = check.data;
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-slate-200 p-3 text-sm dark:border-slate-800">
      <div className="flex flex-wrap items-center gap-3">
        <GhostButton onClick={() => check.mutate()} disabled={check.isPending}>
          {check.isPending ? 'Checking…' : 'Check integrity'}
        </GhostButton>
        <span className="text-slate-600 dark:text-slate-400">
          Each entry is numbered and sealed with the one before it, and the database refuses changes.
        </span>
      </div>
      {check.error && <ErrorText error={check.error} />}
      {result && (
        <div role="status" className="flex flex-col gap-1">
          {result.ok ? (
            <p className="font-semibold text-green-800 dark:text-green-400">
              Intact: {result.entries.toLocaleString()} entries
              {result.first_seq != null && ` (no. ${result.first_seq} to ${result.last_seq})`}, none changed
              or missing.
            </p>
          ) : (
            <>
              <p className="font-semibold text-red-700 dark:text-red-400">
                {result.problems.length} problem{result.problems.length === 1 ? '' : 's'} found:
              </p>
              <ul className="list-disc pl-5">
                {result.problems.map((p) => (
                  <li key={p.id}>
                    Entry {p.seq} ({dateTime(p.created_at)}): {p.problem}
                  </li>
                ))}
              </ul>
            </>
          )}
          {result.starts_after_purge && (
            <p className="text-slate-600 dark:text-slate-400">
              Older entries were removed by the retention setting; that removal is itself an entry.
            </p>
          )}
          {result.head && (
            <p className="flex flex-wrap items-center gap-2 text-slate-600 dark:text-slate-400">
              Latest seal: <code className="font-mono text-xs break-all">{result.head}</code>
              <CopyButton value={result.head} aria-label="Copy the latest seal" />
              <span>Keep a copy elsewhere to prove later that nothing before it changed.</span>
            </p>
          )}
        </div>
      )}
    </div>
  );
}

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
      <ChainCheck />
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
      <ScrollArea label="Audit entries">
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
      </ScrollArea>
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
