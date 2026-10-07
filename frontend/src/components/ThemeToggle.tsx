import { useState } from 'react';

const KEY = 'glasshaus.theme';

export function ThemeToggle() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'));

  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle('dark', next);
    try {
      localStorage.setItem(KEY, next ? 'dark' : 'light');
    } catch {
      /* storage unavailable: theme still applies for this session */
    }
  };

  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={dark}
      className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 dark:border-slate-600 dark:hover:bg-slate-800"
    >
      Dark mode
    </button>
  );
}
