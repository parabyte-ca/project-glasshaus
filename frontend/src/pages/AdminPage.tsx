import { lazy, Suspense } from 'react';
import { useSearchParams } from 'react-router';

import { useAuth } from '../auth/useAuth';
import { TabPanel, Tabs } from '../components/ui';
import { usePageTitle } from '../lib/pageTitle';

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
  ai: [
    'AI assistant',
    lazy(() => import('../components/admin/AiSettings').then((m) => ({ default: m.AiSettings }))),
  ],
  backups: [
    'Backups',
    lazy(() => import('../components/admin/Backups').then((m) => ({ default: m.Backups }))),
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
  usePageTitle(`${current[0]} · Administration`);
  if (user.org_role !== 'owner' && user.org_role !== 'admin') {
    return <p role="alert">Administration is for organization owners and admins.</p>;
  }
  const Panel = current[1];
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold">Administration</h1>
      <Tabs
        label="Administration sections"
        idBase="admin"
        tabs={(Object.keys(TABS) as Tab[]).map((key) => [key, TABS[key][0]] as const)}
        selected={TABS[tab] ? tab : 'people'}
        onSelect={(key) => setParams({ tab: key })}
      />
      <TabPanel idBase="admin" selected={TABS[tab] ? tab : 'people'}>
        <Suspense fallback={<p role="status">Loading…</p>}>
          <Panel />
        </Suspense>
      </TabPanel>
    </div>
  );
}
