import { describe, expect, it } from 'vitest';

import { fields, statuses, task, user } from '../test/mockApi';
import type { CustomField, Status, Task, User } from '../api/client';
import { formatValue, groupTasks, patchForGroup, positionBetween } from './grouping';
import { keysFor } from './realtime';

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
  it('invalidates task, comments and activity for task events', () => {
    expect(keysFor({ type: 'task.updated', aggregate_id: 't1', project_id: 'p1' })).toEqual([
      ['activity'],
      ['tasks', 'p1'],
      ['task', 't1'],
      ['comments', 't1'],
    ]);
    expect(keysFor({ type: 'notification.created' })).toEqual([['notifications']]);
  });
});
