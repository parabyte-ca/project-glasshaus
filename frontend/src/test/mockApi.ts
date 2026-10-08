import { vi } from 'vitest';

type Handler = (req: Request) => unknown | Promise<unknown>;
export interface Route {
  method: string;
  path: string | RegExp;
  status?: number;
  body?: unknown;
  handler?: Handler;
}

export const json = (body: unknown, status = 200) =>
  new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'content-type': status >= 400 ? 'application/problem+json' : 'application/json' },
  });

/** Route fetch() calls by method + path; unmatched calls fail the test loudly. */
export function mockApi(routes: Route[]) {
  const calls: Request[] = [];
  const spy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const req =
      input instanceof Request ? input : new Request(new URL(String(input), 'http://localhost'), init);
    calls.push(req.clone());
    const { pathname } = new URL(req.url);
    const route = routes.find(
      (r) =>
        r.method === req.method && (typeof r.path === 'string' ? r.path === pathname : r.path.test(pathname)),
    );
    if (!route) throw new Error(`unmocked ${req.method} ${pathname}`);
    const body = route.handler ? await route.handler(req) : route.body;
    return json(body === undefined ? {} : body, route.status ?? 200);
  });
  return { calls, spy };
}

export const user = {
  id: 'u1',
  email: 'ada@example.com',
  name: 'Ada Lovelace',
  org_role: 'owner',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  last_login_at: null,
};

export const statuses = [
  { id: 's-todo', name: 'To do', category: 'todo', color: '#64748b', position: 0 },
  { id: 's-done', name: 'Done', category: 'done', color: '#16a34a', position: 1 },
];

export const project = {
  id: 'p1',
  workspace_id: 'w1',
  key: 'WEB',
  name: 'Website',
  description: '',
  archived_at: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  my_role: 'admin',
  auto_schedule: false,
  statuses,
};

export function task(n: number, title = `Task ${n}`) {
  return {
    id: `t${n}`,
    key: `WEB-${n}`,
    project_id: 'p1',
    number: n,
    title,
    description: '',
    status: statuses[0],
    priority: 'none',
    assignee_id: 'u1',
    reporter_id: 'u1',
    parent_id: null,
    start_date: null,
    due_date: '2026-02-01',
    estimate_minutes: null,
    tags: [],
    custom_fields: { f1: 's1' },
    position: n,
    completed_at: null,
    deleted_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    version: 1,
  };
}

export const fields = [
  {
    id: 'f1',
    project_id: 'p1',
    name: 'Severity',
    type: 'select',
    description: '',
    required: false,
    options: [
      { id: 's1', label: 'Sev 1', color: '#ff0000' },
      { id: 's2', label: 'Sev 2', color: '#00ff00' },
    ],
    position: 1,
    created_at: '2026-01-01T00:00:00Z',
  },
];

export const baseRoutes: Route[] = [
  { method: 'GET', path: '/api/v1/projects/p1/fields', body: fields },
  { method: 'GET', path: '/api/v1/projects/p1/views', body: [] },
  { method: 'GET', path: '/api/v1/notifications/unread-count', body: { unread: 0 } },
  {
    method: 'GET',
    path: '/api/v1/version',
    body: { name: 'Project Glasshaus', version: '9.9.9', build: 'abc' },
  },
  { method: 'GET', path: '/api/v1/projects', body: [project] },
  {
    method: 'GET',
    path: '/api/v1/workspaces',
    body: [{ id: 'w1', name: 'Main', slug: 'main', description: '', created_at: '' }],
  },
  { method: 'GET', path: '/api/v1/users', body: [user] },
  { method: 'GET', path: '/api/v1/projects/by-key/WEB', body: project },
  { method: 'GET', path: '/api/v1/project-templates', body: [] },
  { method: 'GET', path: '/api/v1/timer', body: null },
  { method: 'GET', path: '/api/v1/time-entries', body: { items: [], next_cursor: null } },
  { method: 'GET', path: '/api/v1/tokens', body: [] },
  { method: 'GET', path: '/api/v1/oauth/apps', body: [] },
  { method: 'GET', path: '/api/v1/calendar-feed', body: { url: null, created_at: null, last_used_at: null } },
  { method: 'GET', path: '/api/v1/auth/sso/providers', body: [] },
];
