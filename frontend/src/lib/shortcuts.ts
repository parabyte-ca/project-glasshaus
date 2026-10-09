import { useEffect } from 'react';
import { useNavigate } from 'react-router';

/** "g" then a key goes to a section (two-key sequences, as in GitHub and Gmail). */
export const GO_TO: Record<string, [string, string]> = {
  h: ['/', 'Home'],
  d: ['/dashboards', 'Dashboards'],
  r: ['/reports', 'Reports'],
  t: ['/time', 'Time'],
  w: ['/workload', 'Workload'],
  p: ['/portfolios', 'Portfolios'],
  o: ['/goals', 'Goals'],
  a: ['/account', 'Account'],
};

export const SHORTCUTS: [string, string][] = [
  ['Ctrl K / ⌘ K', 'Open the command palette (search, go to, ask)'],
  ['/', 'Search tasks in this project (or open the palette)'],
  ['c', 'Add a task in this project'],
  ...Object.entries(GO_TO).map(([key, [, label]]): [string, string] => [`g then ${key}`, `Go to ${label}`]),
  ['?', 'Show keyboard shortcuts'],
  ['Esc', 'Close a dialog or drawer'],
];

function typing(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
}

function focusShortcut(name: string): boolean {
  const el = document.querySelector<HTMLElement>(`[data-shortcut="${name}"]`);
  if (!el) return false;
  el.focus();
  return true;
}

/** Global keyboard shortcuts. Single-key shortcuts are ignored while typing in a field. */
export function useShortcuts({ palette, help }: { palette: () => void; help: () => void }) {
  const navigate = useNavigate();
  useEffect(() => {
    let pendingG = 0;
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        palette();
        return;
      }
      if (e.ctrlKey || e.metaKey || e.altKey || typing(e.target) || e.defaultPrevented) return;
      if (document.querySelector('[aria-modal="true"]')) return;
      const now = Date.now();
      const target = GO_TO[e.key];
      if (pendingG && now - pendingG < 1200 && target) {
        pendingG = 0;
        e.preventDefault();
        navigate(target[0]);
        return;
      }
      pendingG = 0;
      if (e.key === 'g') pendingG = now;
      else if (e.key === '?') {
        e.preventDefault();
        help();
      } else if (e.key === '/') {
        e.preventDefault();
        if (!focusShortcut('search')) palette();
      } else if (e.key === 'c' && focusShortcut('new-task')) {
        e.preventDefault();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [navigate, palette, help]);
}
