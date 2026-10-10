import { lazy, Suspense, useState, type ReactNode } from 'react';
import { createBrowserRouter, Route, RouterProvider, Routes } from 'react-router';

import { AuthProvider } from './auth/AuthContext';
import { ConfirmProvider } from './components/Confirm';
import { Layout } from './components/Layout';
import { NotFound } from './components/PageState';
import { Toaster } from './components/Toaster';
import { HomePage } from './pages/HomePage';
// Not lazy: My tasks must open offline even if it was never visited.
import { MyTasksPage } from './pages/MyTasksPage';
import { ProjectPage } from './pages/ProjectPage';

const AccountPage = lazy(() => import('./pages/AccountPage').then((m) => ({ default: m.AccountPage })));
const ProjectSettingsPage = lazy(() =>
  import('./pages/ProjectSettingsPage').then((m) => ({ default: m.ProjectSettingsPage })),
);
const TimePage = lazy(() => import('./pages/TimePage').then((m) => ({ default: m.TimePage })));
const WorkloadPage = lazy(() => import('./pages/WorkloadPage').then((m) => ({ default: m.WorkloadPage })));
const ProjectAssistantPage = lazy(() =>
  import('./pages/ProjectAssistantPage').then((m) => ({ default: m.ProjectAssistantPage })),
);
const ImportPage = lazy(() => import('./pages/ImportPage').then((m) => ({ default: m.ImportPage })));
const ProjectReportPage = lazy(() =>
  import('./pages/ProjectReportPage').then((m) => ({ default: m.ProjectReportPage })),
);
const DashboardsPage = lazy(() =>
  import('./pages/DashboardsPage').then((m) => ({ default: m.DashboardsPage })),
);
const PortfoliosPage = lazy(() =>
  import('./pages/PortfoliosPage').then((m) => ({ default: m.PortfoliosPage })),
);
const ConsentPage = lazy(() => import('./pages/ConsentPage').then((m) => ({ default: m.ConsentPage })));
const AdminPage = lazy(() => import('./pages/AdminPage').then((m) => ({ default: m.AdminPage })));
const ReportsPage = lazy(() => import('./pages/ReportsPage').then((m) => ({ default: m.ReportsPage })));
const TeamPage = lazy(() => import('./pages/TeamPage').then((m) => ({ default: m.TeamPage })));
const AboutPage = lazy(() => import('./pages/AboutPage').then((m) => ({ default: m.AboutPage })));
const GoalsPage = lazy(() => import('./pages/GoalsPage').then((m) => ({ default: m.GoalsPage })));

function Lazy({ children }: { children: ReactNode }) {
  return <Suspense fallback={<p role="status">Loading…</p>}>{children}</Suspense>;
}

function Root() {
  return (
    <>
      <AuthProvider>
        <ConfirmProvider>
          <Routes>
            <Route
              path="oauth/consent"
              element={
                <Lazy>
                  <ConsentPage />
                </Lazy>
              }
            />
            <Route element={<Layout />}>
              <Route index element={<HomePage />} />
              <Route
                path="account"
                element={
                  <Suspense fallback={<p role="status">Loading…</p>}>
                    <AccountPage />
                  </Suspense>
                }
              />
              <Route path="projects/:projectKey" element={<ProjectPage />} />
              <Route
                path="projects/:projectKey/import"
                element={
                  <Lazy>
                    <ImportPage />
                  </Lazy>
                }
              />
              <Route
                path="projects/:projectKey/assistant"
                element={
                  <Lazy>
                    <ProjectAssistantPage />
                  </Lazy>
                }
              />
              <Route
                path="projects/:projectKey/settings"
                element={
                  <Suspense fallback={<p role="status">Loading…</p>}>
                    <ProjectSettingsPage />
                  </Suspense>
                }
              />
              <Route
                path="admin"
                element={
                  <Lazy>
                    <AdminPage />
                  </Lazy>
                }
              />
              <Route
                path="time"
                element={
                  <Lazy>
                    <TimePage />
                  </Lazy>
                }
              />
              <Route
                path="workload"
                element={
                  <Lazy>
                    <WorkloadPage />
                  </Lazy>
                }
              />
              <Route
                path="dashboards"
                element={
                  <Lazy>
                    <DashboardsPage />
                  </Lazy>
                }
              />
              <Route
                path="dashboards/:dashboardId"
                element={
                  <Lazy>
                    <DashboardsPage />
                  </Lazy>
                }
              />
              <Route
                path="portfolios"
                element={
                  <Lazy>
                    <PortfoliosPage />
                  </Lazy>
                }
              />
              <Route
                path="portfolios/:portfolioId"
                element={
                  <Lazy>
                    <PortfoliosPage />
                  </Lazy>
                }
              />
              <Route path="my" element={<MyTasksPage />} />
              <Route
                path="about"
                element={
                  <Lazy>
                    <AboutPage />
                  </Lazy>
                }
              />
              <Route
                path="team"
                element={
                  <Lazy>
                    <TeamPage />
                  </Lazy>
                }
              />
              <Route
                path="reports"
                element={
                  <Lazy>
                    <ReportsPage />
                  </Lazy>
                }
              />
              <Route
                path="reports/:reportId"
                element={
                  <Lazy>
                    <ReportsPage />
                  </Lazy>
                }
              />
              <Route
                path="goals"
                element={
                  <Lazy>
                    <GoalsPage />
                  </Lazy>
                }
              />
              <Route
                path="projects/:projectKey/report"
                element={
                  <Lazy>
                    <ProjectReportPage />
                  </Lazy>
                }
              />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
          <Toaster />
        </ConfirmProvider>
      </AuthProvider>
    </>
  );
}

export default function App() {
  // A data router (one splat route around the routes above) so pages can warn before leaving with
  // unsaved changes (useBlocker). Created once per mount, from the address the page opened at.
  const [router] = useState(() => createBrowserRouter([{ path: '*', element: <Root /> }]));
  return <RouterProvider router={router} />;
}
