import { useQuery } from '@tanstack/react-query';

import { getVersion } from './api/client';
import { ThemeToggle } from './components/ThemeToggle';

export default function App() {
  const version = useQuery({ queryKey: ['version'], queryFn: getVersion, staleTime: Infinity });

  return (
    <div className="flex min-h-screen flex-col bg-white text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:rounded focus:bg-sky-700 focus:px-3 focus:py-2 focus:text-white"
      >
        Skip to content
      </a>
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <span className="text-lg font-semibold">Project Glasshaus</span>
        <ThemeToggle />
      </header>
      <main id="main" className="mx-auto w-full max-w-3xl flex-1 px-4 py-12">
        <h1 className="text-2xl font-bold">Welcome to Project Glasshaus</h1>
        <p className="mt-2 text-slate-600 dark:text-slate-400">
          Self-hosted project management. Views, automation and AI tooling arrive in upcoming releases.
        </p>
      </main>
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
