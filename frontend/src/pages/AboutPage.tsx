import { useQuery } from '@tanstack/react-query';

import { api, getVersion, unwrap } from '../api/client';
import { TextLink, linkClass } from '../components/ui';
import { usePageTitle } from '../lib/pageTitle';

type Package = { name: string; version: string; license: string };

function Packages({ title, packages }: { title: string; packages: Package[] | undefined }) {
  return (
    <details className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
      <summary className="cursor-pointer font-semibold">
        {title} {packages ? `(${packages.length})` : ''}
      </summary>
      {packages ? (
        <ul className="mt-2 columns-1 text-sm sm:columns-2">
          {packages.map((p) => (
            <li key={`${p.name}@${p.version}`} className="break-inside-avoid">
              {p.name} {p.version}: <span className="text-slate-600 dark:text-slate-400">{p.license}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm">Not available.</p>
      )}
    </details>
  );
}

/** Version, source code (AGPL-3.0 section 13), how personal data is handled, and third-party notices. */
export function AboutPage() {
  usePageTitle('About and privacy');
  const version = useQuery({ queryKey: ['version'], queryFn: getVersion, staleTime: Infinity });
  const server = useQuery({
    queryKey: ['licenses', 'server'],
    queryFn: () => unwrap(api.GET('/api/v1/licenses')),
    staleTime: Infinity,
  });
  const web = useQuery({
    queryKey: ['licenses', 'web'],
    queryFn: async () => {
      const r = await fetch('/licenses.json');
      if (!r.ok) throw new Error('not available');
      return (await r.json()) as Package[];
    },
    staleTime: Infinity,
    retry: false,
  });
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <h1 className="text-2xl font-bold">About and privacy</h1>
      <section aria-labelledby="about-h" className="flex flex-col gap-2">
        <h2 id="about-h" className="text-lg font-semibold">
          Project Glasshaus
        </h2>
        {version.data && (
          <p>
            Version {version.data.version} ({version.data.build}). Free software under the{' '}
            <a className={linkClass} href="https://www.gnu.org/licenses/agpl-3.0.html" rel="noreferrer">
              GNU Affero General Public License v3
            </a>
            : you may get, study, change and share its source code.{' '}
            {version.data.source && (
              <a className={linkClass} href={version.data.source} rel="noreferrer">
                Source code for this server
              </a>
            )}
          </p>
        )}
      </section>

      <section aria-labelledby="privacy-h" className="flex flex-col gap-2 text-sm">
        <h2 id="privacy-h" className="text-lg font-semibold">
          Your personal data
        </h2>
        <p>
          Your organization runs this server and decides how it is used; ask its admins about its privacy
          policy. Glasshaus itself keeps:
        </p>
        <ul className="list-disc pl-5">
          <li>
            your name, email, role, working hours and, if your organization syncs a directory, job title,
            department and manager;
          </li>
          <li>the work you do: tasks, comments, time logged, and a history of changes;</li>
          <li>sign-ins: when, from which IP address and browser (deleted 90 days after the session ends);</li>
          <li>
            an audit log of administrative and security actions, sealed so it cannot be changed, kept as long
            as your organization sets.
          </li>
        </ul>
        <p>
          Nothing is sent elsewhere unless your organization turns it on: an AI provider (for the assistant,
          only when enabled), Slack or Microsoft Teams posts, webhooks, email, push notifications through your
          browser’s push service, and Microsoft Entra ID or another identity provider for single sign-on and
          provisioning.
        </p>
        <p>
          You can download your data from <TextLink to="/account">Account</TextLink>. Admins can export or
          erase a person’s data; erasing keeps the work but removes who did it.
        </p>
      </section>

      <section aria-labelledby="notices-h" className="flex flex-col gap-2">
        <h2 id="notices-h" className="text-lg font-semibold">
          Third-party software
        </h2>
        <p className="text-sm">
          Glasshaus is built on open-source software. Each package keeps its own licence.
        </p>
        <Packages title="Server" packages={server.data} />
        <Packages title="Web app" packages={web.data} />
      </section>
    </div>
  );
}
