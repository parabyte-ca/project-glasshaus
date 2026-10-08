import { lazy, Suspense } from 'react';
import { useSearchParams } from 'react-router';

import { useAuth } from '../auth/useAuth';

const TABS = {
  people: ['People', lazy(() => import('../components/admin/People').then((m) => ({ default: m.People })))],
  sso: [
    'Single sign-on',
    lazy(() => import('../components/admin/SingleSignOn').then((m) => ({ default: m.SingleSignOn }))),
  ],
  provisioning: [
    'Provisioning',
    lazy(() => import('../components/admin/Provisioning').then((m) => ({ default: m.Provisioning }))),
  ],
  integrations: [
    'Integrations',
    lazy(() => import('../components/admin/Integrations').then((m) => ({ default: m.Integrations }))),
  ],
  audit: [
    'Audit log',
    lazy(() => import('../components/admin/AuditLog').then((m) => ({ default: m.AuditLog }))),
  ],
  data: [
    'Data & retention',
    lazy(() => import('../components/admin/DataRetention').then((m) => ({ default: m.DataRetention }))),
  ],
} as const;
type Tab = keyof typeof TABS;

export function AdminPage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = (params.get('tab') as Tab | null) ?? 'people';
  const current = TABS[tab] ?? TABS.people;
  if (user.org_role !== 'owner' && user.org_role !== 'admin') {
    return <p role="alert">Administration is for organization owners and admins.</p>;
  }
  const Panel = current[1];
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold">Administration</h1>
      <div
        role="tablist"
        aria-label="Administration sections"
        className="flex flex-wrap gap-1 border-b border-slate-200 dark:border-slate-700"
      >
        {(Object.keys(TABS) as Tab[]).map((key) => (
          <button
            key={key}
            role="tab"
            type="button"
            aria-selected={key === tab}
            className={`-mb-px border-b-2 px-3 py-1.5 text-sm ${key === tab ? 'border-sky-700 font-medium' : 'border-transparent text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100'}`}
            onClick={() => setParams({ tab: key })}
          >
            {TABS[key][0]}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        <Suspense fallback={<p role="status">Loading…</p>}>
          <Panel />
        </Suspense>
      </div>
    </div>
  );
}
