import { useQuery } from '@tanstack/react-query';
import { Link, NavLink, Outlet } from 'react-router';

import { api, getVersion, unwrap } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { useLiveUpdates } from '../lib/realtime';
import { NotificationsBell } from './NotificationsBell';
import { ThemeToggle } from './ThemeToggle';
import { GhostButton } from './ui';

export function Layout() {
  const { user, logout } = useAuth();
  useLiveUpdates();
  const version = useQuery({ queryKey: ['version'], queryFn: getVersion, staleTime: Infinity });
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => unwrap(api.GET('/api/v1/projects')) });

  return (
    <div className="flex min-h-screen flex-col bg-white text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:rounded focus:bg-sky-700 focus:px-3 focus:py-2 focus:text-white"
      >
        Skip to content
      </a>
      <header className="flex items-center justify-between gap-4 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <Link to="/" className="text-lg font-semibold">
          Project Glasshaus
        </Link>
        <div className="flex items-center gap-2">
          <Link
            to="/account"
            className="hidden text-sm text-slate-600 hover:underline sm:inline dark:text-slate-400"
            aria-label={`Account settings for ${user.name}`}
          >
            {user.name}
          </Link>
          <NotificationsBell />
          <ThemeToggle />
          <GhostButton onClick={logout}>Sign out</GhostButton>
        </div>
      </header>
      <div className="flex flex-1 flex-col md:flex-row">
        <nav
          aria-label="Projects"
          className="border-b border-slate-200 p-4 md:w-60 md:border-r md:border-b-0 dark:border-slate-800"
        >
          <h2 className="mb-2 text-xs font-semibold tracking-wide text-slate-600 uppercase dark:text-slate-400">
            Projects
          </h2>
          <ul className="flex flex-col gap-1">
            {projects.data?.map((p) => (
              <li key={p.id}>
                <NavLink
                  to={`/projects/${p.key}`}
                  className={({ isActive }) =>
                    `block rounded px-2 py-1 text-sm hover:bg-slate-100 dark:hover:bg-slate-800 ${isActive ? 'bg-slate-100 font-medium dark:bg-slate-800' : ''}`
                  }
                >
                  <span className="mr-2 font-mono text-xs text-slate-600 dark:text-slate-400">{p.key}</span>
                  {p.name}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <main id="main" className="flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
      <footer className="px-4 py-3 text-xs text-slate-600 dark:text-slate-400" aria-live="polite">
        {version.isSuccess && (
          <span data-testid="version">
            v{version.data.version} ({version.data.build})
          </span>
        )}
        {version.isError && <span role="alert">API unavailable</span>}
      </footer>
    </div>
  );
}
