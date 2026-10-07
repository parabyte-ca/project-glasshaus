// Apply the saved/OS theme before first paint to avoid a flash (external file keeps CSP free of inline scripts).
try {
  const t = localStorage.getItem('glasshaus.theme');
  const dark = t ? t === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.classList.toggle('dark', dark);
} catch {
  /* storage unavailable */
}
