import { useId, useRef, type ReactNode } from 'react';

import { useModal } from './useModal';

/** Modal dialog: traps focus, closes on Escape or a backdrop click, and restores focus on close. */
export function Dialog({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const id = useId();
  useModal(ref, onClose);
  return (
    <div
      role="presentation"
      className="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/50 p-4 pt-[10vh]"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
        tabIndex={-1}
        className={`flex max-h-[80vh] w-full flex-col gap-3 overflow-auto rounded-lg bg-white p-4 shadow-xl dark:bg-slate-900 ${wide ? 'max-w-2xl' : 'max-w-lg'}`}
      >
        <h2 id={id} className="text-lg font-semibold">
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
}
