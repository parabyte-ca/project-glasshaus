import type { Task } from '../api/client';
import { addDays, parseDay } from './dates';

/** Shift (or resize) a task by whole days, keeping whichever dates it has. */
export function shiftPatch(task: Task, days: number, mode: 'move' | 'resize'): Record<string, string | null> {
  if (mode === 'resize') {
    const due = task.due_date ?? task.start_date!;
    const next = addDays(due, days);
    const floor = task.start_date ?? next;
    return { due_date: parseDay(next) < parseDay(floor) ? floor : next };
  }
  return {
    start_date: task.start_date ? addDays(task.start_date, days) : null,
    due_date: task.due_date ? addDays(task.due_date, days) : null,
  };
}

/** Tasks whose start..due range covers ``day`` (single-date tasks show on that date). */
export function tasksOn(tasks: Task[], day: string): Task[] {
  const d = parseDay(day);
  return tasks.filter((t) => {
    const s = t.start_date ?? t.due_date;
    const e = t.due_date ?? t.start_date;
    return s !== null && e !== null && parseDay(s) <= d && d <= parseDay(e);
  });
}
