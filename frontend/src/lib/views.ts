import type { ViewConfig } from '../api/client';

export const OPEN = ['backlog', 'todo', 'in_progress'] as const;

export const DEFAULT_CONFIG: ViewConfig = {
  filters: { status_categories: [...OPEN], top_level_only: false },
  group_by: null,
  sort: 'position',
  descending: false,
  sort_field: null,
  columns: ['key', 'title', 'status', 'priority', 'assignee', 'due_date'],
};

/** Default configuration per layout. */
export function defaultConfig(kind: string): ViewConfig {
  // Boards, timelines and calendars show completed work in context; lists and tables default to open work.
  if (!['board', 'timeline', 'calendar'].includes(kind)) return DEFAULT_CONFIG;
  return { ...DEFAULT_CONFIG, filters: { ...DEFAULT_CONFIG.filters, status_categories: null } };
}
