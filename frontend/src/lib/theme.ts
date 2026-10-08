const KEY = 'glasshaus.theme';
export const THEME_EVENT = 'glasshaus:theme';

/** Switch light/dark everywhere (the toggle button and the command palette share this). */
export function toggleTheme() {
  const next = !document.documentElement.classList.contains('dark');
  document.documentElement.classList.toggle('dark', next);
  try {
    localStorage.setItem(KEY, next ? 'dark' : 'light');
  } catch {
    /* storage unavailable: theme still applies for this session */
  }
  window.dispatchEvent(new Event(THEME_EVENT));
}
