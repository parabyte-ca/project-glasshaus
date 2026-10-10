import { useQuery } from '@tanstack/react-query';
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router';

import { api, getVersion, unwrap } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { useOnline } from '../lib/offline';
import { useLiveUpdates } from '../lib/realtime';
import { SHORTCUTS, useShortcuts } from '../lib/shortcuts';
import { NotificationsBell } from './NotificationsBell';
import { OnboardingChecklist } from './onboarding/OnboardingChecklist';
import { useStartTour } from './onboarding/useStartTour';
import { ThemeToggle } from './ThemeToggle';
import { TimerIndicator } from './TimeTracking';
import { GhostButton } from './ui';

const CommandPalette = lazy(() => import('./CommandPalette').then((m) => ({ default: m.CommandPalette })));
const ShortcutHelp = lazy(() => import('./CommandPalette').then((m) => ({ default: m.ShortcutHelp })));

const SECTIONS = [
  ['/', 'Home'],
  ['/my', 'My tasks'],
  ['/dashboards', 'Dashboards'],
  ['/reports', 'Reports'],
  ['/time', 'Time'],
  ['/workload', 'Workload'],
  ['/portfolios', 'Portfolios'],
  ['/goals', 'Goals'],
] as const;

export function Layout() {
  const { user, logout, offline: serverUnreachable } = useAuth();
  const offline = !useOnline() || !!serverUnreachable;
  useLiveUpdates();
  const version = useQuery({ queryKey: ['version'], queryFn: getVersion, staleTime: Infinity });
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => unwrap(api.GET('/api/v1/projects')) });
  const [overlay, setOverlay] = useState<'palette' | 'help' | null>(null);
  const openPalette = useCallback(() => setOverlay('palette'), []);
  const openHelp = useCallback(() => setOverlay('help'), []);
  const closeOverlay = useCallback(() => setOverlay(null), []);
  useShortcuts({ palette: openPalette, help: openHelp });
  const startTour = useStartTour();
  const mac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);
  // Phones: the navigation is a menu behind a button instead of a list above every page.
  const [menuOpen, setMenuOpen] = useState(false);
  const { pathname } = useLocation();
  const [menuPath, setMenuPath] = useState(pathname);
  if (menuPath !== pathname) {
    setMenuPath(pathname);
    setMenuOpen(false);
  }
  useFocusOnNavigation(pathname);

  return (
    <div className="flex min-h-screen flex-col">
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
          <Link
            to="/"
            className="truncate text-lg font-semibold tracking-tight text-sky-700 dark:text-sky-400"
          >
            <span className="hidden text-slate-600 sm:inline dark:text-slate-400">Project </span>Glasshaus
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
              ...SECTIONS.slice(0, 2),
              // Managers (people with reports in the directory) get My team.
              ...((user.direct_reports ?? 0) > 0 ? ([['/team', 'My team']] as const) : []),
              ...SECTIONS.slice(2),
              ...(user.org_role === 'owner' || user.org_role === 'admin'
                ? ([['/admin', 'Admin']] as const)
                : []),
            ].map(([to, label]) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={to === '/'}
                  className={({ isActive }) =>
                    `block rounded border-l-2 px-2 py-1 text-sm hover:bg-slate-100 dark:hover:bg-slate-800 ${isActive ? 'border-accent-500 bg-slate-100 font-semibold dark:bg-slate-800' : 'border-transparent'}`
                  }
                >
                  {label}
                </NavLink>
              </li>
            ))}
          </ul>
          <h2 className="mb-2 text-xs font-bold tracking-wide text-accent-700 uppercase dark:text-accent-400">
            Projects
          </h2>
          <ul className="flex flex-col gap-1">
            {projects.data?.map((p) => (
              <li key={p.id}>
                <NavLink
                  to={`/projects/${p.key}`}
                  className={({ isActive }) =>
                    `block rounded border-l-2 px-2 py-1 text-sm hover:bg-slate-100 dark:hover:bg-slate-800 ${isActive ? 'border-accent-500 bg-slate-100 font-semibold dark:bg-slate-800' : 'border-transparent'}`
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
          {offline && pathname !== '/my' && (
            <p role="status" className="mb-4 rounded-lg border border-amber-400 p-3 text-sm">
              <strong>You’re offline.</strong> This page needs a connection;{' '}
              <Link to="/my" className="underline">
                My tasks
              </Link>{' '}
              works offline.
            </p>
          )}
          <Outlet />
        </main>
      </div>
      <Suspense fallback={null}>
        {overlay === 'palette' && <CommandPalette onClose={closeOverlay} onHelp={openHelp} />}
        {overlay === 'help' && <ShortcutHelp onClose={closeOverlay} shortcuts={SHORTCUTS} />}
      </Suspense>
      <OnboardingChecklist />
      <footer className="flex gap-3 px-4 py-3 text-xs text-slate-600 dark:text-slate-400" aria-live="polite">
        <button type="button" onClick={openHelp} className="min-h-6 rounded underline">
          Keyboard shortcuts (?)
        </button>
        {startTour && (
          <button type="button" onClick={startTour} className="min-h-6 rounded underline">
            Product tour
          </button>
        )}
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

/**
 * After moving to another page, put focus on its heading (as a full page load would put it at the
 * top), so keyboard and screen reader users start from the new page instead of the old link.
 * Pages that load lazily get their heading a moment later; give up if the person has moved on.
 */
function useFocusOnNavigation(pathname: string) {
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const main = document.getElementById('main');
    if (!main) return;
    const startedOn = document.activeElement;
    const tryFocus = () => {
      const moved = document.activeElement !== startedOn && document.activeElement !== document.body;
      if (moved && !main.contains(document.activeElement)) return true; // the person went elsewhere
      if (main.querySelector('[role="dialog"]')) return true; // a dialog (task drawer) owns focus
      const heading = main.querySelector<HTMLElement>('h1');
      if (!heading) return false;
      heading.tabIndex = -1;
      heading.focus({ preventScroll: true });
      return true;
    };
    if (tryFocus()) return;
    const observer = new MutationObserver(() => tryFocus() && observer.disconnect());
    observer.observe(main, { childList: true, subtree: true });
    const stop = setTimeout(() => observer.disconnect(), 3000);
    return () => {
      observer.disconnect();
      clearTimeout(stop);
    };
  }, [pathname]);
}
