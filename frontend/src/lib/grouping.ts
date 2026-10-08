import type { CustomField, Status, Task, User } from '../api/client';

export const PRIORITIES = ['urgent', 'high', 'medium', 'low', 'none'] as const;

export interface Group {
  key: string;
  label: string;
  tasks: Task[];
}

/** Group tasks for list/board views. Empty groups are kept for status (board columns) only. */
export function groupTasks(
  tasks: Task[],
  groupBy: string | null | undefined,
  ctx: { statuses: Status[]; users: User[]; fields: CustomField[] },
): Group[] {
  if (!groupBy) return [{ key: 'all', label: 'All tasks', tasks }];
  const buckets = new Map<string, Group>();
  const add = (key: string, label: string, task?: Task) => {
    if (!buckets.has(key)) buckets.set(key, { key, label, tasks: [] });
    if (task) buckets.get(key)!.tasks.push(task);
  };

  if (groupBy === 'status') {
    for (const s of ctx.statuses) add(s.id, s.name);
    for (const t of tasks) add(t.status.id, t.status.name, t);
    return [...buckets.values()];
  }
  if (groupBy === 'priority') {
    for (const p of PRIORITIES) add(p, p[0]!.toUpperCase() + p.slice(1));
    for (const t of tasks) add(t.priority, t.priority, t);
    return [...buckets.values()].filter((g) => g.tasks.length > 0);
  }
  if (groupBy === 'assignee') {
    const names = new Map(ctx.users.map((u) => [u.id, u.name]));
    for (const t of tasks) {
      const id = t.assignee_id ?? 'none';
      add(id, t.assignee_id ? (names.get(t.assignee_id) ?? 'Unknown') : 'Unassigned', t);
    }
    return [...buckets.values()].sort((a, b) =>
      a.key === 'none' ? 1 : b.key === 'none' ? -1 : a.label.localeCompare(b.label),
    );
  }
  if (groupBy.startsWith('cf:')) {
    const field = ctx.fields.find((f) => f.id === groupBy.slice(3));
    if (!field) return [{ key: 'all', label: 'All tasks', tasks }];
    for (const o of field.options) add(o.id, o.label);
    for (const t of tasks) {
      const value = t.custom_fields[field.id];
      const values = Array.isArray(value) ? value : value === undefined ? [] : [value];
      if (values.length === 0) add('none', `No ${field.name}`, t);
      for (const v of values) add(String(v), field.options.find((o) => o.id === v)?.label ?? String(v), t);
    }
    return [...buckets.values()].filter(
      (g) => g.tasks.length > 0 || field.options.some((o) => o.id === g.key),
    );
  }
  return [{ key: 'all', label: 'All tasks', tasks }];
}

/** Position between two neighbours (fractional ordering used by drag and drop). */
export function positionBetween(before?: number, after?: number): number {
  if (before === undefined && after === undefined) return 1024;
  if (before === undefined) return after! - 1024;
  if (after === undefined) return before + 1024;
  return (before + after) / 2;
}

export function formatValue(field: CustomField, value: unknown, users: User[]): string {
  if (value === undefined || value === null || value === '') return '—';
  switch (field.type) {
    case 'select':
      return field.options.find((o) => o.id === value)?.label ?? String(value);
    case 'multi_select':
      return (value as string[]).map((v) => field.options.find((o) => o.id === v)?.label ?? v).join(', ');
    case 'user':
      return users.find((u) => u.id === value)?.name ?? 'Unknown';
    case 'checkbox':
      return value ? 'Yes' : 'No';
    default:
      return String(value);
  }
}

/** Patch that moves a task into a column for the board's grouping. */
export function patchForGroup(groupBy: string, groupKey: string): Record<string, unknown> {
  if (groupBy === 'status') return { status_id: groupKey };
  if (groupBy === 'priority') return { priority: groupKey };
  if (groupBy === 'assignee') return { assignee_id: groupKey === 'none' ? null : groupKey };
  if (groupBy.startsWith('cf:'))
    return { custom_fields: { [groupBy.slice(3)]: groupKey === 'none' ? null : groupKey } };
  return {};
}
