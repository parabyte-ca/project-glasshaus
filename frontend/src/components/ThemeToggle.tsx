import { useEffect, useState } from 'react';

import { THEME_EVENT, toggleTheme } from '../lib/theme';

export function ThemeToggle() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'));
  useEffect(() => {
    const sync = () => setDark(document.documentElement.classList.contains('dark'));
    window.addEventListener(THEME_EVENT, sync);
    return () => window.removeEventListener(THEME_EVENT, sync);
  }, []);

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-pressed={dark}
      className="rounded-md border border-slate-300 px-2 py-1.5 sm:px-3 text-sm hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 dark:border-slate-600 dark:hover:bg-slate-800"
    >
      {/* Phones: a symbol, so the header keeps room for the name. */}
      <span aria-hidden="true" className="sm:hidden">
        ◐
      </span>
      <span className="sr-only sm:not-sr-only">Dark mode</span>
    </button>
  );
}
