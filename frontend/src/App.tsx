import { lazy, Suspense, type ReactNode } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router';

import { AuthProvider } from './auth/AuthContext';
import { ConfirmProvider } from './components/Confirm';
import { Layout } from './components/Layout';
import { NotFound } from './components/PageState';
import { Toaster } from './components/Toaster';
import { HomePage } from './pages/HomePage';
import { ProjectPage } from './pages/ProjectPage';

const AccountPage = lazy(() => import('./pages/AccountPage').then((m) => ({ default: m.AccountPage })));
const ProjectSettingsPage = lazy(() =>
  import('./pages/ProjectSettingsPage').then((m) => ({ default: m.ProjectSettingsPage })),
);
const TimePage = lazy(() => import('./pages/TimePage').then((m) => ({ default: m.TimePage })));
const WorkloadPage = lazy(() => import('./pages/WorkloadPage').then((m) => ({ default: m.WorkloadPage })));
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
const GoalsPage = lazy(() => import('./pages/GoalsPage').then((m) => ({ default: m.GoalsPage })));

function Lazy({ children }: { children: ReactNode }) {
  return <Suspense fallback={<p role="status">Loading…</p>}>{children}</Suspense>;
}

export default function App() {
  return (
    <BrowserRouter>
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
    </BrowserRouter>
  );
}
