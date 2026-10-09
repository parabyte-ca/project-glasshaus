import { useEffect, useId, useRef, useState, type ReactNode } from 'react';

import { useOnboarding } from '../../lib/onboarding';

/**
 * A pulsing hotspot next to an advanced feature, for people who skipped the tour. Hover, focus or
 * click opens a short tip; "Got it" hides this tip for good. Escape closes it.
 */
export function Beacon({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  const { state, update } = useOnboarding();
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const tipId = useId();
  const root = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        setOpen(false);
        setPinned(false);
      }
    };
    const onClick = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) {
        setOpen(false);
        setPinned(false);
      }
    };
    document.addEventListener('keydown', onKey, true);
    document.addEventListener('mousedown', onClick);
    return () => {
      document.removeEventListener('keydown', onKey, true);
      document.removeEventListener('mousedown', onClick);
    };
  }, [open]);

  if (!state || state.tour !== 'skipped' || state.dismissed_tips.includes(id)) return null;
  return (
    <span
      ref={root}
      className="relative inline-flex"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => !pinned && setOpen(false)}
    >
      <button
        type="button"
        aria-label={`Tip: ${title}`}
        aria-expanded={open}
        aria-controls={open ? tipId : undefined}
        onClick={() => {
          setPinned(!pinned || !open);
          setOpen(!(pinned && open));
        }}
        className="relative flex h-6 w-6 items-center justify-center rounded-full focus-visible:outline-2 focus-visible:outline-sky-600"
      >
        <span className="absolute h-3 w-3 rounded-full bg-sky-500 opacity-75 motion-safe:animate-ping" />
        <span className="relative h-2.5 w-2.5 rounded-full bg-sky-600 dark:bg-sky-400" />
      </button>
      {open && (
        <span
          id={tipId}
          role="dialog"
          aria-label={title}
          className="absolute top-full left-1/2 z-30 mt-2 flex w-64 -translate-x-1/2 flex-col gap-2 rounded-lg border border-slate-200 bg-white p-3 text-left text-sm font-normal shadow-lg dark:border-slate-700 dark:bg-slate-900"
        >
          <span className="font-semibold">{title}</span>
          <span className="text-slate-700 dark:text-slate-300">{children}</span>
          <button
            type="button"
            onClick={() => update({ dismiss_tip: id })}
            className="self-end rounded-md border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-sky-600 dark:border-slate-600 dark:hover:bg-slate-800"
          >
            Got it
          </button>
        </span>
      )}
    </span>
  );
}
