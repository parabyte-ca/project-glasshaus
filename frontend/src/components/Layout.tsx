import { useQuery } from '@tanstack/react-query';
import { lazy, Suspense, useCallback, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router';

import { api, getVersion, unwrap } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { useLiveUpdates } from '../lib/realtime';
import { SHORTCUTS, useShortcuts } from '../lib/shortcuts';
import { NotificationsBell } from './NotificationsBell';
import { ThemeToggle } from './ThemeToggle';
import { TimerIndicator } from './TimeTracking';
import { GhostButton } from './ui';

const CommandPalette = lazy(() => import('./CommandPalette').then((m) => ({ default: m.CommandPalette })));
const ShortcutHelp = lazy(() => import('./CommandPalette').then((m) => ({ default: m.ShortcutHelp })));

const SECTIONS = [
  ['/', 'Home'],
  ['/dashboards', 'Dashboards'],
  ['/time', 'Time'],
  ['/workload', 'Workload'],
  ['/portfolios', 'Portfolios'],
  ['/goals', 'Goals'],
] as const;

export function Layout() {
  const { user, logout } = useAuth();
  useLiveUpdates();
  const version = useQuery({ queryKey: ['version'], queryFn: getVersion, staleTime: Infinity });
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => unwrap(api.GET('/api/v1/projects')) });
  const [overlay, setOverlay] = useState<'palette' | 'help' | null>(null);
  const openPalette = useCallback(() => setOverlay('palette'), []);
  const openHelp = useCallback(() => setOverlay('help'), []);
  const closeOverlay = useCallback(() => setOverlay(null), []);
  useShortcuts({ palette: openPalette, help: openHelp });
  const mac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);
  // Phones: the navigation is a menu behind a button instead of a list above every page.
  const [menuOpen, setMenuOpen] = useState(false);
  const { pathname } = useLocation();
  const [menuPath, setMenuPath] = useState(pathname);
  if (menuPath !== pathname) {
    setMenuPath(pathname);
    setMenuOpen(false);
  }

  return (
    <div className="flex min-h-screen flex-col bg-white text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:rounded focus:bg-sky-700 focus:px-3 focus:py-2 focus:text-white"
      >
        Skip to content
      </a>
      <header className="flex items-center justify-between gap-2 border-b border-slate-200 px-3 py-2 sm:gap-4 sm:px-4 sm:py-3 dark:border-slate-800">
        <div className="flex min-w-0 items-center gap-2">
          <GhostButton
            className="md:hidden"
            aria-expanded={menuOpen}
            aria-controls="main-nav"
            onClick={() => setMenuOpen((open) => !open)}
          >
            Menu
          </GhostButton>
          <Link to="/" className="truncate text-lg font-semibold">
            <span className="hidden sm:inline">Project </span>Glasshaus
          </Link>
        </div>
        <div className="flex shrink-0 items-center gap-1 sm:gap-2">
          <GhostButton
            onClick={openPalette}
            aria-keyshortcuts={mac ? 'Meta+K' : 'Control+K'}
            className="px-2 sm:px-3"
          >
            Search <kbd className="ml-1 hidden font-mono text-xs sm:inline">{mac ? '⌘K' : 'Ctrl K'}</kbd>
          </GhostButton>
          <Link
            to="/account"
            className="hidden text-sm text-slate-600 hover:underline sm:inline dark:text-slate-400"
            aria-label={`Account settings for ${user.name}`}
          >
            {user.name}
          </Link>
          <TimerIndicator />
          <NotificationsBell />
          <ThemeToggle />
          <GhostButton onClick={logout} className="hidden sm:inline-block">
            Sign out
          </GhostButton>
        </div>
      </header>
      <div className="flex flex-1 flex-col md:flex-row">
        <nav
          id="main-nav"
          aria-label="Projects"
          className={`${menuOpen ? 'block' : 'hidden'} border-b border-slate-200 p-4 md:block md:w-60 md:border-r md:border-b-0 dark:border-slate-800`}
        >
          <ul className="mb-4 flex flex-col gap-1">
            {[
              ...SECTIONS,
              ...(user.org_role === 'owner' || user.org_role === 'admin'
                ? ([['/admin', 'Admin']] as const)
                : []),
            ].map(([to, label]) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={to === '/'}
                  className={({ isActive }) =>
                    `block rounded px-2 py-1 text-sm hover:bg-slate-100 dark:hover:bg-slate-800 ${isActive ? 'bg-slate-100 font-medium dark:bg-slate-800' : ''}`
                  }
                >
                  {label}
                </NavLink>
              </li>
            ))}
          </ul>
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
          <div className="mt-4 flex flex-col gap-2 border-t border-slate-200 pt-4 sm:hidden dark:border-slate-800">
            <Link
              to="/account"
              className="rounded px-2 py-1 text-sm hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              Account ({user.name})
            </Link>
            <GhostButton onClick={logout}>Sign out</GhostButton>
          </div>
        </nav>
        <main id="main" className="min-w-0 flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
      <Suspense fallback={null}>
        {overlay === 'palette' && <CommandPalette onClose={closeOverlay} onHelp={openHelp} />}
        {overlay === 'help' && <ShortcutHelp onClose={closeOverlay} shortcuts={SHORTCUTS} />}
      </Suspense>
      <footer className="flex gap-3 px-4 py-3 text-xs text-slate-600 dark:text-slate-400" aria-live="polite">
        <button type="button" onClick={openHelp} className="underline">
          Keyboard shortcuts (?)
        </button>
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
