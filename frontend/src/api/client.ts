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
export type Rule = Schemas['RuleRead'];
export type RuleInput = Schemas['RuleCreate'];
export type RuleAction = Schemas['Action-Input'];
export type RuleCondition = Schemas['Condition-Input'];
export type RuleTrigger = Schemas['Trigger-Input'];
export type Run = Schemas['RunRead'];
export type Recurring = Schemas['RecurringRead'];
export type ScheduleSpec = Schemas['ScheduleSpec-Input'];
export type Onboarding = Schemas['OnboardingRead'];
export type OnboardingUpdate = Schemas['OnboardingUpdate'];
export type ProjectTemplate = Schemas['TemplateRead'];
export type TimeEntry = Schemas['TimeEntryRead'];
export type Timer = Schemas['TimerRead'];
export type Timesheet = Schemas['Timesheet'];
export type TimeReport = Schemas['TimeReport'];
export type Workload = Schemas['Workload'];
export type ProjectReport = Schemas['ProjectReport'];
export type ProjectHealth = Schemas['ProjectHealth'];
export type Dashboard = Schemas['DashboardRead'];
export type Widget = Schemas['Widget-Input'];
export type Portfolio = Schemas['PortfolioRead'];
export type PortfolioDetail = Schemas['PortfolioDetail'];
export type Objective = Schemas['ObjectiveRead'];
export type KeyResult = Schemas['KeyResultRead'];
export type SavedReport = Schemas['SavedReportRead'];
export type ReportDefinition = Schemas['ReportDefinition-Input'];
export type ReportResult = Schemas['ReportResult'];
export type ReportOverrides = Schemas['ReportOverrides'];

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly code?: string,
    /** Problems with individual request fields, by field name (a 422 from request validation). */
    public readonly fields: Record<string, string> = {},
  ) {
    super(message);
  }
}

type FieldProblem = { loc?: unknown[]; msg?: string };

/** Map validation errors ({loc: ["body", "name"], msg}) to {name: msg}. */
function fieldProblems(errors: unknown): Record<string, string> {
  const fields: Record<string, string> = {};
  if (!Array.isArray(errors)) return fields;
  for (const e of errors as FieldProblem[]) {
    const loc = (e.loc ?? []).filter((part) => typeof part === 'string' && part !== 'body');
    const name = loc[loc.length - 1];
    if (typeof name === 'string' && e.msg && !fields[name]) {
      fields[name] = e.msg.replace(/^Value error, /, '');
    }
  }
  return fields;
}

/** The server's message for one form field, if the last request failed because of it. */
export function fieldError(error: unknown, name: string): string | undefined {
  return error instanceof ApiError ? error.fields[name] : undefined;
}

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export function csrfToken(): string {
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
/** What to tell people when a request fails for a reason they can't fix by changing their input. */
export function plainStatus(status: number): string {
  if (status === 0) return "Can't reach Glasshaus. Check your connection and try again.";
  if (status === 429) return 'Too many requests at once. Wait a moment and try again.';
  if (status === 502 || status === 503 || status === 504)
    return 'Glasshaus is unavailable right now (it may be updating). Try again in a minute.';
  if (status >= 500)
    return 'Something went wrong on the server. Try again, or tell your administrator if it keeps happening.';
  if (status === 404) return "That couldn't be found. It may have been deleted or moved.";
  if (status === 403) return "You don't have permission to do that.";
  return `The request failed (${status}).`;
}

export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: Awaited<typeof call>;
  try {
    result = await call;
  } catch (cause) {
    // fetch itself failed ("Failed to fetch"): offline, or the server is unreachable.
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    throw new ApiError(0, plainStatus(0));
  }
  const { data, error, response } = result;
  if (error !== undefined || !response.ok) {
    const problem = (error ?? {}) as { detail?: unknown; code?: string; errors?: unknown };
    const fields = fieldProblems(problem.errors);
    const named = Object.keys(fields).length > 0;
    // 4xx carry the server's explanation; for the rest, a plain sentence beats "Bad Gateway".
    let detail =
      typeof problem.detail === 'string' && response.status < 500 && response.status !== 429
        ? problem.detail
        : plainStatus(response.status);
    if (named && detail === 'request validation failed') {
      // Name the fields, so the message helps even where a form doesn't mark the field itself.
      detail = Object.entries(fields)
        .map(([name, msg]) => `${name.charAt(0).toUpperCase()}${name.slice(1).replace(/_/g, ' ')}: ${msg}`)
        .join('; ');
    }
    throw new ApiError(response.status, detail || `HTTP ${response.status}`, problem.code, fields);
  }
  return data as T;
}

export const getVersion = () => unwrap(api.GET('/api/v1/version'));
