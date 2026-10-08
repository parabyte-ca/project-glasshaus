export const dateTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '—';

export const table = 'w-full text-left text-sm';
export const th = 'border-b border-slate-200 px-2 py-1.5 font-medium dark:border-slate-700';
export const td = 'border-b border-slate-100 px-2 py-1.5 align-top dark:border-slate-800';
