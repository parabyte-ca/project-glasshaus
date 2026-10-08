import { useVirtualizer } from '@tanstack/react-virtual';
import { useRef } from 'react';

import type { Task } from '../api/client';
import { Assignee } from '../components/TaskBits';
import { Select } from '../components/ui';
import { formatValue, PRIORITIES } from '../lib/grouping';
import type { ViewProps } from './types';

const ROW_HEIGHT = 44;
/** Below this many rows the table renders fully (cheap, and friendlier to screen readers). */
export const VIRTUALIZE_ABOVE = 100;
const LABELS: Record<string, string> = {
  key: 'Key',
  title: 'Title',
  status: 'Status',
  priority: 'Priority',
  assignee: 'Assignee',
  start_date: 'Start',
  due_date: 'Due',
  tags: 'Tags',
  estimate: 'Estimate',
  updated_at: 'Updated',
};

export function TableView({ tasks, project, fields, users, config, onOpen, onUpdate }: ViewProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const columns = config.columns ?? ['key', 'title', 'status', 'priority', 'assignee', 'due_date'];
  // eslint-disable-next-line react-hooks/incompatible-library -- TanStack Virtual returns unstable functions by design
  const virtualizer = useVirtualizer({
    count: tasks.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 10,
    initialRect: { width: 1000, height: 600 },
  });
  const virtual = tasks.length > VIRTUALIZE_ABOVE;
  const items = virtual
    ? virtualizer.getVirtualItems()
    : tasks.map((_, index) => ({ index, start: index * ROW_HEIGHT, end: (index + 1) * ROW_HEIGHT }));
  const padTop = items[0]?.start ?? 0;
  const padBottom = virtual ? virtualizer.getTotalSize() - (items.at(-1)?.end ?? 0) : 0;

  const label = (col: string) =>
    col.startsWith('cf:')
      ? (fields.find((f) => f.id === col.slice(3))?.name ?? 'Field')
      : (LABELS[col] ?? col);

  const cell = (task: Task, col: string) => {
    switch (col) {
      case 'key':
        return <span className="font-mono text-xs">{task.key}</span>;
      case 'title':
        return (
          <button type="button" className="text-left hover:underline" onClick={() => onOpen(task)}>
            {task.title}
          </button>
        );
      case 'status':
        return (
          <Select
            aria-label={`Status of ${task.key}`}
            value={task.status.id}
            onChange={(e) => onUpdate(task, { status_id: e.target.value })}
          >
            {project.statuses.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </Select>
        );
      case 'priority':
        return (
          <Select
            aria-label={`Priority of ${task.key}`}
            value={task.priority}
            onChange={(e) => onUpdate(task, { priority: e.target.value })}
          >
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </Select>
        );
      case 'assignee':
        return <Assignee id={task.assignee_id} users={users} />;
      case 'start_date':
        return task.start_date ?? '—';
      case 'due_date':
        return task.due_date ?? '—';
      case 'tags':
        return task.tags.join(', ') || '—';
      case 'estimate':
        return task.estimate_minutes ? `${Math.round(task.estimate_minutes / 6) / 10} h` : '—';
      case 'updated_at':
        return new Date(task.updated_at).toLocaleDateString();
      default: {
        const field = fields.find((f) => f.id === col.slice(3));
        return field ? formatValue(field, task.custom_fields[field.id], users) : '—';
      }
    }
  };

  return (
    <div
      ref={scrollRef}
      className="max-h-[70vh] overflow-auto rounded-lg border border-slate-200 dark:border-slate-800"
    >
      <table className="w-full text-left text-sm" aria-rowcount={tasks.length + 1}>
        <caption className="sr-only">Tasks in {project.name}</caption>
        <thead className="sticky top-0 z-10 bg-white text-xs text-slate-600 uppercase dark:bg-slate-950 dark:text-slate-400">
          <tr aria-rowindex={1}>
            {columns.map((col) => (
              <th key={col} scope="col" className="border-b border-slate-200 px-3 py-2 dark:border-slate-800">
                {label(col)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {padTop > 0 && (
            <tr aria-hidden>
              <td style={{ height: padTop }} colSpan={columns.length} />
            </tr>
          )}
          {items.map((row) => {
            const task = tasks[row.index]!;
            return (
              <tr
                key={task.id}
                aria-rowindex={row.index + 2}
                style={{ height: ROW_HEIGHT }}
                className="border-b border-slate-100 dark:border-slate-900"
              >
                {columns.map((col) => (
                  <td key={col} className="px-3 py-1 whitespace-nowrap">
                    {cell(task, col)}
                  </td>
                ))}
              </tr>
            );
          })}
          {padBottom > 0 && (
            <tr aria-hidden>
              <td style={{ height: padBottom }} colSpan={columns.length} />
            </tr>
          )}
        </tbody>
      </table>
      {tasks.length === 0 && (
        <p className="p-6 text-center text-slate-600 dark:text-slate-400">No tasks match.</p>
      )}
    </div>
  );
}
