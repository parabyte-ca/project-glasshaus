import type { ReactNode } from 'react';

export function Section({
  title,
  children,
  intro,
}: {
  title: string;
  intro?: ReactNode;
  children: ReactNode;
}) {
  const id = `h-${title.toLowerCase().replace(/[^a-z]+/g, '-')}`;
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <h2 id={id} className="text-lg font-semibold">
        {title}
      </h2>
      {intro && <p className="max-w-3xl text-sm text-slate-600 dark:text-slate-400">{intro}</p>}
      {children}
    </section>
  );
}

export function SecretOnce({ label, value }: { label: string; value: string }) {
  return (
    <div role="status" className="rounded border border-amber-400 bg-amber-50 p-3 text-sm dark:bg-amber-950">
      <p className="font-semibold">{label} (shown once; copy it now)</p>
      <code className="block break-all select-all">{value}</code>
    </div>
  );
}

export function Copyable({ value }: { value: string }) {
  return (
    <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs break-all dark:bg-slate-800">{value}</code>
  );
}
