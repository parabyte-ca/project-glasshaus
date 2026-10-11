/** Words people read for the values the API uses. */
export const PRIORITY_LABEL: Record<string, string> = {
  urgent: 'Urgent',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
  none: 'None',
};

export const priorityLabel = (p: string) => PRIORITY_LABEL[p] ?? p;

/** " · Urgent" or " · High" for the priorities worth calling out in a list; nothing otherwise. */
export const notablePriority = (p: string) =>
  p === 'urgent' || p === 'high' ? ` · ${priorityLabel(p)}` : '';
