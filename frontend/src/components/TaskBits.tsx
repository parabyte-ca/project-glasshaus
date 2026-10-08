import type { Status, Task, User } from '../api/client';

const PRIORITY_STYLE: Record<string, string> = {
  urgent: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200',
  high: 'bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-200',
  medium: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200',
  low: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  none: 'hidden',
};

export function StatusPill({ status }: { status: Status }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs whitespace-nowrap">
      <span aria-hidden className="h-2 w-2 rounded-full" style={{ backgroundColor: status.color }} />
      {status.name}
    </span>
  );
}

export function PriorityBadge({ priority }: { priority: Task['priority'] }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs ${PRIORITY_STYLE[priority] ?? ''}`}>{priority}</span>
  );
}

export function Assignee({ id, users }: { id: string | null; users: User[] }) {
  if (!id) return <span className="text-slate-500 dark:text-slate-400">Unassigned</span>;
  return <span>{users.find((u) => u.id === id)?.name ?? 'Unknown'}</span>;
}
