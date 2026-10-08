import createClient from 'openapi-fetch';

import type { components, paths } from './schema';

export type Schemas = components['schemas'];
export type Task = Schemas['TaskRead'];
export type Project = Schemas['ProjectRead'];
export type ProjectDetail = Schemas['ProjectDetail'];
export type User = Schemas['UserRead'];
export type Workspace = Schemas['WorkspaceRead'];
export type VersionInfo = Schemas['VersionInfo'];
export type Status = Schemas['StatusRead'];
export type CustomField = Schemas['FieldRead'];
export type Comment = Schemas['CommentRead'];
export type Notification = Schemas['NotificationRead'];
export type ActivityItem = Schemas['ActivityItem'];
export type SavedView = Schemas['ViewRead'];
export type ViewConfig = Schemas['ViewConfig-Input'];
export type ViewKind = Schemas['ViewKind'];
export type Priority = Schemas['Priority'];
export type Dependency = Schemas['DependencyRead'];
export type DependencyType = Schemas['DependencyType'];
export type Schedule = Schemas['ScheduleRead'];
export type Baseline = Schemas['BaselineRead'];
export type BaselineVariance = Schemas['BaselineVariance'];
export type ScheduleWarning = Schemas['ScheduleWarning'];

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly code?: string,
  ) {
    super(message);
  }
}

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)gh_csrf=([^;]+)/);
  return match?.[1] ? decodeURIComponent(match[1]) : '';
}

let refreshing: Promise<boolean> | null = null;

function refreshSession(): Promise<boolean> {
  refreshing ??= fetch('/api/v1/auth/refresh', { method: 'POST', credentials: 'same-origin' })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

/** Adds the CSRF header to unsafe requests and transparently refreshes an expired session once. */
export async function sessionFetch(input: Request): Promise<Response> {
  const prepare = () => {
    const req = input.clone();
    if (UNSAFE.has(req.method)) req.headers.set('X-CSRF-Token', csrfToken());
    return new Request(req, { credentials: 'same-origin' });
  };
  const response = await fetch(prepare());
  if (response.status !== 401 || input.url.includes('/api/v1/auth/')) return response;
  return (await refreshSession()) ? fetch(prepare()) : response;
}

export const api = createClient<paths>({ baseUrl: window.location.origin, fetch: sessionFetch });

/** Unwrap an openapi-fetch result, throwing ApiError (RFC 9457 detail) on failure. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call;
  if (error !== undefined || !response.ok) {
    const problem = (error ?? {}) as { detail?: unknown; code?: string };
    const detail = typeof problem.detail === 'string' ? problem.detail : response.statusText;
    throw new ApiError(response.status, detail || `HTTP ${response.status}`, problem.code);
  }
  return data as T;
}

export const getVersion = () => unwrap(api.GET('/api/v1/version'));
