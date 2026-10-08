import type { Rule, RuleTrigger, Schemas } from '../api/client';

type TriggerType = Schemas['TriggerType'];

export const TRIGGERS: { value: TriggerType; label: string }[] = [
  { value: 'task_created', label: 'Task created' },
  { value: 'task_updated', label: 'Task updated' },
  { value: 'status_changed', label: 'Status changed' },
  { value: 'comment_created', label: 'Comment added' },
  { value: 'due_soon', label: 'Due date approaching' },
  { value: 'scheduled', label: 'On a schedule' },
];
export const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

export function triggerLabel(t: RuleTrigger | Rule['trigger']): string {
  const base = TRIGGERS.find((x) => x.value === t.type)?.label ?? t.type;
  if (t.type === 'status_changed' && t.to_category) return `${base} → ${t.to_category.replace('_', ' ')}`;
  if (t.type === 'due_soon') return `${t.days_before ?? 0} days before due`;
  if (t.type === 'scheduled' && t.schedule) {
    const s = t.schedule;
    const at = `${String(s.hour ?? 9).padStart(2, '0')}:${String(s.minute ?? 0).padStart(2, '0')}`;
    if (s.frequency === 'weekly') return `Every ${WEEKDAYS[s.weekday ?? 0]} at ${at}`;
    if (s.frequency === 'monthly') return `Monthly on day ${s.day} at ${at}`;
    return `Daily at ${at}`;
  }
  if (t.type === 'task_updated' && t.field) return `${base} (${t.field})`;
  return base;
}
