import { useEffect, useId, useRef, type ReactNode } from 'react';

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

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
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const node = ref.current;
    if (node && !node.contains(document.activeElement)) {
      (node.querySelector<HTMLElement>('[autofocus], [data-autofocus]') ?? node).focus();
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        close.current();
      } else if (e.key === 'Tab' && node) {
        const items = [...node.querySelectorAll<HTMLElement>(FOCUSABLE)];
        const first = items[0];
        const last = items[items.length - 1];
        if (!first || !last) return;
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      previous?.focus?.();
    };
  }, []);
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
