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

/** Default configuration per layout: boards show every status column, including completed work. */
export function defaultConfig(kind: string): ViewConfig {
  if (kind !== 'board') return DEFAULT_CONFIG;
  return { ...DEFAULT_CONFIG, filters: { ...DEFAULT_CONFIG.filters, status_categories: null } };
}
