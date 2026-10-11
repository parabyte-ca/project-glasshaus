import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';

import { fields, statuses, task, user } from '../test/mockApi';
import type { CustomField, Status, Task, User } from '../api/client';
import { formatValue, groupTasks, patchForGroup, positionBetween } from './grouping';
import { triggerLabel } from './automation';
import { plainStatus } from '../api/client';
import { rescueFocus } from './focus';
import { niceScale } from './chartScale';
import { currentQuarter, formatMinutes, hours, mondayOf, parseDuration } from './format';
import { InvalidationBatcher, PATCH_LIMIT, keysFor, patchable } from './realtime';
import { addDays, monthGrid, parseDay, formatDay } from './dates';
import { shiftPatch, tasksOn } from './schedule';

const ctx = { statuses: statuses as Status[], users: [user] as User[], fields: fields as CustomField[] };
const t = (n: number, extra: Partial<Task> = {}) => ({ ...task(n), ...extra }) as Task;

describe('groupTasks', () => {
  it('keeps every status as a column, even empty ones', () => {
    const groups = groupTasks([t(1)], 'status', ctx);
    expect(groups.map((g) => [g.label, g.tasks.length])).toEqual([
      ['To do', 1],
      ['Done', 0],
    ]);
  });

  it('groups by assignee with unassigned last', () => {
    const groups = groupTasks([t(1, { assignee_id: null }), t(2)], 'assignee', ctx);
    expect(groups.map((g) => g.label)).toEqual(['Ada Lovelace', 'Unassigned']);
  });

  it('groups by a select custom field', () => {
    const groups = groupTasks([t(1), t(2, { custom_fields: {} })], 'cf:f1', ctx);
    expect(groups.map((g) => [g.label, g.tasks.length])).toEqual([
      ['Sev 1', 1],
      ['Sev 2', 0],
      ['No Severity', 1],
    ]);
  });
});

describe('board helpers', () => {
  it('computes fractional positions', () => {
    expect(positionBetween()).toBe(1024);
    expect(positionBetween(1, 3)).toBe(2);
    expect(positionBetween(undefined, 10)).toBe(-1014);
    expect(positionBetween(10)).toBe(1034);
  });

  it('maps a column to a task patch', () => {
    expect(patchForGroup('status', 's1')).toEqual({ status_id: 's1' });
    expect(patchForGroup('assignee', 'none')).toEqual({ assignee_id: null });
    expect(patchForGroup('cf:f1', 's2')).toEqual({ custom_fields: { f1: 's2' } });
  });

  it('formats custom field values', () => {
    expect(formatValue(fields[0] as CustomField, 's2', [])).toBe('Sev 2');
    expect(formatValue(fields[0] as CustomField, undefined, [])).toBe('—');
  });
});

describe('live update keys', () => {
  it('patches edited tasks and invalidates the rest', () => {
    const edit = { type: 'task.updated', aggregate_id: 't1', project_id: 'p1' };
    expect(patchable(edit)).toBe(true);
    expect(keysFor(edit)).toEqual([
      ['my-tasks'],
      ['task', 't1'],
      ['comments', 't1'],
      ['activity', 'task', 't1'],
      ['onboarding'],
    ]);
    // New and deleted tasks change which tasks a list holds: refetch it.
    expect(keysFor({ type: 'task.created', aggregate_id: 't2', project_id: 'p1' })[0]).toEqual([
      'tasks',
      'p1',
    ]);
    // Lists don't show comments.
    expect(keysFor({ type: 'comment.created', aggregate_id: 't1', project_id: 'p1' })).not.toContainEqual([
      'tasks',
      'p1',
    ]);
    expect(keysFor({ type: 'notification.created' })).toEqual([['notifications']]);
  });

  it('invalidates each key once per burst, without cancelling refetches in flight', () => {
    vi.useFakeTimers();
    try {
      const client = new QueryClient();
      const spy = vi.spyOn(client, 'invalidateQueries').mockResolvedValue();
      const batcher = new InvalidationBatcher(client, 400);
      for (let i = 0; i < 50; i++) {
        batcher.add(keysFor({ type: 'task.created', aggregate_id: `t${i % 2}`, project_id: 'p1' }));
      }
      expect(spy).not.toHaveBeenCalled();
      vi.advanceTimersByTime(400);
      // tasks list, my tasks and onboarding once, plus task/comments/activity for each of the two tasks.
      expect(spy).toHaveBeenCalledTimes(9);
      expect(spy).toHaveBeenCalledWith({ queryKey: ['tasks', 'p1'], exact: false }, { cancelRefetch: false });
      spy.mockClear();
      batcher.add([['projects']]);
      batcher.dispose();
      vi.advanceTimersByTime(1000);
      expect(spy).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it('swaps an edited task into open lists instead of refetching them', async () => {
    const client = new QueryClient();
    const mk = (id: string, title: string) => ({ id, title, project_id: 'p1' }) as unknown as Task;
    client.setQueryData(['tasks', 'p1', { filters: {} }], { items: [mk('t1', 'Old'), mk('t2', 'Other')] });
    client.setQueryData(['tasks', 'p1', { filters: { assignee_id: 'u1' } }], { items: [mk('t1', 'Old')] });
    client.setQueryData(['tasks', 'p1', 'warnings'], []);
    const spy = vi.spyOn(client, 'invalidateQueries').mockResolvedValue();
    const fetch = vi.fn(async () => mk('t1', 'New'));
    const batcher = new InvalidationBatcher(client, 0, fetch);
    batcher.add([], { projectId: 'p1', taskId: 't1' });
    batcher.add([], { projectId: 'p1', taskId: 't1' }); // the same task twice in a burst: one fetch
    batcher.flush();
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    await vi.waitFor(() =>
      expect(
        client.getQueryData<{ items: Task[] }>(['tasks', 'p1', { filters: {} }])?.items.map((t) => t.title),
      ).toEqual(['New', 'Other']),
    );
    // A filtered list may have gained or lost the task, and the timeline's derived data depends on
    // it: only those are refetched.
    expect(spy).toHaveBeenCalledTimes(2);
    expect(spy).toHaveBeenCalledWith(
      { queryKey: ['tasks', 'p1', { filters: { assignee_id: 'u1' } }], exact: true },
      { cancelRefetch: false },
    );
    expect(spy).toHaveBeenCalledWith(
      { queryKey: ['tasks', 'p1', 'warnings'], exact: true },
      { cancelRefetch: false },
    );
  });

  it('refetches the lists when a burst edits many tasks or the task is gone', async () => {
    const client = new QueryClient();
    client.setQueryData(['tasks', 'p1', { filters: {} }], { items: [] });
    const spy = vi.spyOn(client, 'invalidateQueries').mockResolvedValue();
    const fetch = vi.fn(async () => {
      throw new Error('not found');
    });
    const batcher = new InvalidationBatcher(client, 0, fetch);
    for (let i = 0; i <= PATCH_LIMIT; i++) batcher.add([], { projectId: 'p1', taskId: `t${i}` });
    batcher.flush();
    expect(fetch).not.toHaveBeenCalled();
    expect(spy).toHaveBeenCalledWith({ queryKey: ['tasks', 'p1'], exact: false }, { cancelRefetch: false });
    spy.mockClear();
    batcher.add([], { projectId: 'p1', taskId: 'gone' });
    batcher.flush();
    await vi.waitFor(() =>
      expect(spy).toHaveBeenCalledWith({ queryKey: ['tasks', 'p1'], exact: false }, { cancelRefetch: false }),
    );
  });
});

describe('dates and scheduling helpers', () => {
  it('does date arithmetic in UTC days', () => {
    expect(addDays('2026-02-27', 3)).toBe('2026-03-02');
    expect(formatDay(parseDay('2026-12-31') + 1)).toBe('2027-01-01');
  });

  it('builds Monday-first month grids', () => {
    const grid = monthGrid('2026-03-01');
    expect(grid[0]![0]).toBe('2026-02-23');
    expect(grid.flat()).toContain('2026-03-31');
    expect(grid.every((w) => w.length === 7)).toBe(true);
  });

  it('moves and resizes tasks by days', () => {
    const t = { ...task(1), start_date: '2026-03-02', due_date: '2026-03-04' } as Task;
    expect(shiftPatch(t, 2, 'move')).toEqual({ start_date: '2026-03-04', due_date: '2026-03-06' });
    expect(shiftPatch(t, 1, 'resize')).toEqual({ due_date: '2026-03-05' });
    expect(shiftPatch(t, -5, 'resize')).toEqual({ due_date: '2026-03-02' }); // never before the start
    const dueOnly = { ...task(2), start_date: null, due_date: '2026-03-04' } as Task;
    expect(shiftPatch(dueOnly, -1, 'move')).toEqual({ start_date: null, due_date: '2026-03-03' });
  });

  it('finds tasks spanning a day', () => {
    const span = { ...task(1), start_date: '2026-03-02', due_date: '2026-03-04' } as Task;
    const undated = { ...task(2), start_date: null, due_date: null } as Task;
    expect(tasksOn([span, undated], '2026-03-03').map((t) => t.id)).toEqual(['t1']);
    expect(tasksOn([span], '2026-03-05')).toEqual([]);
  });
});

describe('automation labels', () => {
  it('describes triggers in plain words', () => {
    expect(triggerLabel({ type: 'due_soon', days_before: 2 })).toBe('2 days before due');
    expect(
      triggerLabel({ type: 'scheduled', schedule: { frequency: 'weekly', weekday: 4, hour: 8, minute: 5 } }),
    ).toBe('Every Friday at 08:05');
    expect(triggerLabel({ type: 'task_updated', field: 'tags' })).toBe('Task updated (tags)');
  });
});

describe('durations', () => {
  it('parses the formats people type', () => {
    expect(parseDuration('1h 30m')).toBe(90);
    expect(parseDuration('1.5h')).toBe(90);
    expect(parseDuration('45m')).toBe(45);
    expect(parseDuration('90')).toBe(90);
    expect(parseDuration('1:05')).toBe(65);
    expect(parseDuration('soon')).toBeNull();
    expect(parseDuration('0m')).toBeNull();
  });
  it('formats minutes and weeks', () => {
    expect(formatMinutes(95)).toBe('1h 35m');
    expect(formatMinutes(60)).toBe('1h');
    expect(formatMinutes(5)).toBe('5m');
    expect(hours(90)).toBe('1.5');
    expect(mondayOf('2026-10-11')).toBe('2026-10-05');
    expect(currentQuarter(new Date(2026, 9, 8))).toBe('2026-Q4');
  });
});

describe('chart scale', () => {
  it('picks round tick steps', () => {
    expect(niceScale(25)).toEqual({ max: 40, step: 10 });
    expect(niceScale(9)).toEqual({ max: 20, step: 5 });
    expect(niceScale(3)).toEqual({ max: 4, step: 1 });
    expect(niceScale(0)).toEqual({ max: 4, step: 1 });
    expect(niceScale(130)).toEqual({ max: 200, step: 50 });
  });
});

describe('plainStatus', () => {
  it('says what happened in plain words, not status codes', () => {
    expect(plainStatus(0)).toMatch(/Can't reach Glasshaus/);
    expect(plainStatus(429)).toMatch(/Too many requests/);
    for (const code of [502, 503, 504]) expect(plainStatus(code)).toMatch(/unavailable right now/);
    expect(plainStatus(500)).toMatch(/went wrong on the server/);
    expect(plainStatus(403)).toMatch(/permission/);
    expect(plainStatus(404)).toMatch(/couldn't be found/);
  });
});

describe('rescueFocus', () => {
  it('moves focus to the next control in the list when the focused one is removed', async () => {
    document.body.innerHTML =
      '<section><h2>Queue</h2><ul><li id="a"><button>Approve A</button></li><li><button>Approve B</button></li></ul></section>';
    const first = document.querySelector<HTMLButtonElement>('#a button')!;
    first.focus();
    rescueFocus(first);
    document.getElementById('a')!.remove();
    first.blur(); // jsdom keeps focus on a removed element; browsers drop it to <body>
    await new Promise((r) => setTimeout(r, 0));
    expect(document.activeElement).toHaveTextContent('Approve B');
  });

  it('falls back to the heading when nothing focusable is left', async () => {
    document.body.innerHTML =
      '<section><h2>Queue</h2><ul><li id="a"><button>Approve A</button></li></ul></section>';
    const only = document.querySelector<HTMLButtonElement>('#a button')!;
    only.focus();
    rescueFocus(only);
    document.getElementById('a')!.remove();
    only.blur();
    await new Promise((r) => setTimeout(r, 0));
    expect(document.activeElement?.tagName).toBe('H2');
  });
});
