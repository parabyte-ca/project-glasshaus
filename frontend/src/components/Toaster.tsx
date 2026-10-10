import { dismissToast, useToasts } from '../lib/toast';

/**
 * Short confirmations and background errors. The live regions are always in the page, so screen
 * readers announce each message as it is added (a region created together with its text is often
 * not read).
 */
export function Toaster() {
  const toasts = useToasts();
  const item = (tone: 'info' | 'error') =>
    toasts
      .filter((t) => t.tone === tone)
      .map((t) => (
        <div
          key={t.id}
          className={`pointer-events-auto flex items-center gap-3 rounded-md px-4 py-2 text-sm shadow-lg ${
            tone === 'error'
              ? 'bg-red-700 text-white'
              : 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
          }`}
        >
          <span>{t.message}</span>
          {t.action && (
            <button
              type="button"
              onClick={() => {
                dismissToast(t.id);
                t.action?.run();
              }}
              className="min-h-8 rounded px-2 font-semibold underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-current"
            >
              {t.action.label}
            </button>
          )}
          <button
            type="button"
            aria-label="Dismiss message"
            onClick={() => dismissToast(t.id)}
            className="-mr-2 flex h-6 w-6 items-center justify-center rounded opacity-80 hover:opacity-100 focus-visible:outline-2 focus-visible:outline-white"
          >
            ×
          </button>
        </div>
      ));
  return (
    <div className="pointer-events-none fixed bottom-4 left-1/2 z-[60] flex -translate-x-1/2 flex-col items-center gap-2">
      <div aria-live="polite" className="flex flex-col items-center gap-2">
        {item('info')}
      </div>
      <div aria-live="assertive" className="flex flex-col items-center gap-2">
        {item('error')}
      </div>
    </div>
  );
}
