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

/** Search, filters, grouping and sort live in the address, so links, reloads and Back keep them. */
const PARAM_KEYS = ['q', 'priority', 'group', 'sort', 'done'] as const;
type ParamKey = (typeof PARAM_KEYS)[number];

function encode(config: ViewConfig): Record<ParamKey, string> {
  const filters = config.filters ?? {};
  return {
    q: filters.q ?? '',
    priority: filters.priorities?.[0] ?? '',
    group: config.group_by ?? '',
    sort: config.sort_field ? `cf:${config.sort_field}` : (config.sort ?? 'position'),
    done: filters.status_categories ? '0' : '1',
  };
}

/** The view's configuration with the address's overrides applied. */
export function configWithParams(base: ViewConfig, params: URLSearchParams): ViewConfig {
  const filters = { ...(base.filters ?? {}) };
  const config: ViewConfig = { ...base };
  const q = params.get('q');
  if (q !== null) filters.q = q || null;
  const priority = params.get('priority');
  if (priority !== null) {
    filters.priorities = priority ? [priority as NonNullable<typeof filters.priorities>[number]] : null;
  }
  const group = params.get('group');
  if (group !== null) config.group_by = group || null;
  const sort = params.get('sort');
  if (sort?.startsWith('cf:')) config.sort_field = sort.slice(3);
  else if (sort) Object.assign(config, { sort, sort_field: null });
  const done = params.get('done');
  if (done !== null) filters.status_categories = done === '1' ? null : [...OPEN];
  return { ...config, filters };
}

/** Address parameters for `next`: only what differs from the view's own configuration. */
export function paramsForConfig(
  base: ViewConfig,
  next: ViewConfig,
  current: URLSearchParams,
): URLSearchParams {
  const out = new URLSearchParams(current);
  const from = encode(base);
  const to = encode(next);
  for (const key of PARAM_KEYS) {
    if (from[key] === to[key]) out.delete(key);
    else out.set(key, to[key]);
  }
  return out;
}
