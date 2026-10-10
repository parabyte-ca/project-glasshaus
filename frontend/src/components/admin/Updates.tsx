import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, unwrap } from '../../api/client';
import { useAuth } from '../../auth/useAuth';
import { useConfirm } from '../../lib/confirm';
import { toast } from '../../lib/toast';
import { Markdown } from '../Markdown';
import { Button, ErrorText, GhostButton } from '../ui';
import { Copyable, Section } from './common';
import { dateTime } from './format';

const AGENT = 'sudo ./scripts/upgrade-agent.sh --install';

/** This version, the latest release, and upgrades run by the helper on the server. */
export function Updates() {
  const { user } = useAuth();
  const owner = user.org_role === 'owner';
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: ['admin-updates'],
    queryFn: () => unwrap(api.GET('/api/v1/admin/updates')),
    // While an upgrade runs, follow its progress. The server restarts near the end, so a failed poll
    // just means "still restarting".
    refetchInterval: (q) =>
      q.state.data?.upgrade?.state === 'requested' || q.state.data?.upgrade?.state === 'running'
        ? 4000
        : false,
    retry: (count) => count < 30,
    retryDelay: 4000,
  });
  const check = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/admin/updates/check')),
    onSuccess: (data) => {
      queryClient.setQueryData(['admin-updates'], data);
      toast(
        data.update_available
          ? `Glasshaus ${data.latest?.version} is available.`
          : 'Glasshaus is up to date.',
      );
    },
  });
  const upgrade = useMutation({
    mutationFn: (version: string) => unwrap(api.POST('/api/v1/admin/updates/upgrade', { body: { version } })),
    onSuccess: (data) => {
      queryClient.setQueryData(['admin-updates'], data);
      toast('Upgrade requested. The server starts it within a minute.');
    },
  });
  const s = status.data;
  const running = s?.upgrade?.state === 'requested' || s?.upgrade?.state === 'running';
  const restarting = running && status.isError;

  return (
    <Section
      title="Updates"
      intro={
        <>
          Glasshaus checks once a day for a new release and tells owners and admins. Owners can upgrade from
          here: a helper on the server backs up the database, tries the new release on a copy first, then
          upgrades, and goes back to this version if anything fails.
        </>
      }
    >
      {!restarting && <ErrorText error={status.error ?? check.error ?? upgrade.error} />}
      {s && (
        <>
          <dl className="grid max-w-3xl grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="font-medium">This server</dt>
            <dd>{s.current}</dd>
            <dt className="font-medium">Latest release</dt>
            <dd>
              {s.latest ? (
                <>
                  {s.latest.version}
                  {s.latest.published_at && ` (${dateTime(s.latest.published_at)})`}
                </>
              ) : (
                'Not checked yet'
              )}
            </dd>
            <dt className="font-medium">Last checked</dt>
            <dd>
              {s.checked_at ? dateTime(s.checked_at) : 'Never'}
              {s.check_error && (
                <span className="text-amber-800 dark:text-amber-300"> (failed: {s.check_error})</span>
              )}
            </dd>
          </dl>
          <div className="flex flex-wrap items-center gap-3">
            <GhostButton
              onClick={() => check.mutate()}
              disabled={check.isPending}
              aria-busy={check.isPending}
            >
              {check.isPending ? 'Checking…' : 'Check now'}
            </GhostButton>
            {!s.update_available && s.latest && (
              <p className="flex items-center gap-1 text-sm font-medium text-green-800 dark:text-green-400">
                <span aria-hidden="true">✓</span> Glasshaus is up to date.
              </p>
            )}
          </div>

          {running && (
            <div
              role="status"
              className="max-w-3xl rounded border border-sky-300 p-3 text-sm dark:border-sky-800"
            >
              <p className="font-semibold">
                {s.upgrade!.state === 'requested'
                  ? `Upgrade to ${s.upgrade!.to_version} requested; the server starts it within a minute.`
                  : restarting
                    ? 'Glasshaus is restarting with the new version…'
                    : `Upgrading to ${s.upgrade!.to_version}… This takes a few minutes; you can leave this page.`}
              </p>
            </div>
          )}
          {s.upgrade?.state === 'succeeded' && (
            <p role="status" className="text-sm font-medium text-green-800 dark:text-green-400">
              {s.upgrade.message ?? 'Upgraded.'}{' '}
              {s.upgrade.to_version && s.upgrade.to_version !== __APP_VERSION__ && (
                <button type="button" className="underline" onClick={() => window.location.reload()}>
                  Reload to use it
                </button>
              )}
            </p>
          )}
          {s.upgrade?.state === 'failed' && (
            <p role="alert" className="text-sm text-red-700 dark:text-red-400">
              {s.upgrade.message ?? 'The upgrade stopped.'}
            </p>
          )}

          {s.update_available && s.latest && (
            <section
              aria-labelledby="release-notes"
              className="flex max-w-3xl flex-col gap-2 rounded-lg border border-slate-200 p-4 dark:border-slate-800"
            >
              <h3 id="release-notes" className="font-semibold">
                What's new in {s.latest.version}
              </h3>
              <Markdown text={s.latest.notes || 'No release notes.'} />
              <a
                href={s.latest.url}
                target="_blank"
                rel="noreferrer"
                className="text-sm text-sky-700 underline dark:text-sky-400"
              >
                Release page
              </a>
              {owner ? (
                s.helper.connected ? (
                  <div>
                    <Button
                      disabled={!s.can_upgrade || upgrade.isPending}
                      onClick={async () =>
                        (await confirm({
                          title: `Upgrade to ${s.latest!.version}?`,
                          body: 'Glasshaus backs up the database, checks the new release on a copy, then upgrades. People may see “unavailable” for a minute while it restarts. If anything fails, it goes back to this version.',
                          confirmLabel: 'Upgrade',
                        })) && upgrade.mutate(s.latest!.version)
                      }
                    >
                      Upgrade to {s.latest.version}
                    </Button>
                  </div>
                ) : (
                  <div className="text-sm">
                    <p>
                      To upgrade from here, set up the upgrade helper on the server once (it runs every minute
                      and only acts when you press Upgrade). In the Glasshaus folder on the server, run:
                    </p>
                    <p className="mt-1">
                      <Copyable value={AGENT} />
                    </p>
                    <p className="mt-1 text-slate-600 dark:text-slate-400">
                      {s.helper.configured
                        ? s.helper.last_seen
                          ? `The helper last checked in ${dateTime(s.helper.last_seen)}; it should run every minute.`
                          : 'The helper hasn’t checked in yet.'
                        : 'This server has no upgrade folder yet; the command creates it.'}{' '}
                      Or upgrade from a terminal with <code>sudo ./update.sh</code>.
                    </p>
                  </div>
                )
              ) : (
                <p className="text-sm text-slate-600 dark:text-slate-400">
                  An owner can upgrade from this page.
                </p>
              )}
            </section>
          )}

          {owner && s.log && (
            <details className="max-w-3xl text-sm" open={running}>
              <summary className="cursor-pointer font-medium">Upgrade log</summary>
              <pre className="mt-2 max-h-80 overflow-auto rounded bg-slate-100 p-2 text-xs whitespace-pre-wrap dark:bg-slate-900">
                {s.log}
              </pre>
            </details>
          )}
        </>
      )}
    </Section>
  );
}
