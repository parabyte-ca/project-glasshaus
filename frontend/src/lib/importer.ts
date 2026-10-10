import type { Schemas } from '../api/client';

/** Reading spreadsheets in the browser and turning their rows into import rows for the API. */

export type ImportRow = Schemas['ImportRow'];
export type DateFormat = 'auto' | 'ymd' | 'dmy' | 'mdy';
export type Source = 'spreadsheet' | 'nimble';
export type Sheet = { name: string; rows: string[][] };

export const MAX_ROWS = 5000;

/** Where a column can go. Comments and links accept several columns; the rest take one. */
export const TARGETS = [
  { key: 'external_id', label: 'ID (to update on re-import)' },
  { key: 'title', label: 'Title' },
  { key: 'description', label: 'Description' },
  { key: 'status', label: 'Status' },
  { key: 'priority', label: 'Priority' },
  { key: 'assignee', label: 'Owner (email or name)' },
  { key: 'start_date', label: 'Start date' },
  { key: 'due_date', label: 'Due date' },
  { key: 'estimate', label: 'Estimate (hours)' },
  { key: 'tags', label: 'Tags' },
  { key: 'parent', label: 'Parent ID' },
  { key: 'comments', label: 'Comment' },
  { key: 'links', label: 'Link' },
] as const;
export type Target = (typeof TARGETS)[number]['key'] | `cf:${string}`;
export const MULTI: ReadonlySet<string> = new Set(['comments', 'links']);

// Column names other tools use. Nimble's are a first guess until checked against a real export.
const COMMON: Record<string, string[]> = {
  external_id: ['id', 'key', 'item id', 'issue key', 'task id', 'number'],
  title: ['title', 'name', 'summary', 'task', 'task name', 'subject'],
  description: ['description', 'details', 'notes', 'body'],
  status: ['status', 'state', 'stage', 'column', 'list'],
  priority: ['priority', 'importance'],
  assignee: ['assignee', 'owner', 'assigned to', 'responsible', 'owner email', 'assignee email'],
  start_date: ['start', 'start date', 'starts', 'planned start'],
  due_date: ['due', 'due date', 'deadline', 'end date', 'finish date', 'target date'],
  estimate: ['estimate', 'estimated hours', 'effort', 'original estimate', 'hours'],
  tags: ['tags', 'labels', 'tag', 'label'],
  parent: ['parent', 'parent id', 'parent key', 'epic', 'epic link'],
  comments: ['comment', 'comments', 'last comment'],
  links: ['link', 'links', 'url', 'attachment', 'attachments'],
};
const NIMBLE: Record<string, string[]> = {
  external_id: ['work item id', 'workitem id', 'card id', 'item number', 'item code'],
  title: ['work item name', 'workitem name', 'card title', 'item name'],
  status: ['lane', 'workflow state', 'swimlane', 'stage name'],
  priority: ['class of service'],
  assignee: ['owner name', 'assigned user', 'card owner'],
  start_date: ['planned start date', 'actual start date'],
  due_date: ['planned finish date', 'planned end date', 'target finish date'],
  estimate: ['planned effort', 'estimated effort', 'effort (hours)'],
  parent: ['parent work item id', 'parent card id'],
};

const clean = (s: string) =>
  s
    .toLowerCase()
    .replace(/[_\-.:()]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

/** A first mapping from the header row: known names, then custom fields by their name. */
export function guessMapping(
  headers: string[],
  source: Source,
  fields: { id: string; name: string }[] = [],
): Target[] {
  const taken = new Set<string>();
  return headers.map((header): Target => {
    const h = clean(header);
    const tables = source === 'nimble' ? [NIMBLE, COMMON] : [COMMON];
    for (const table of tables) {
      for (const [target, names] of Object.entries(table)) {
        if (names.includes(h) && (MULTI.has(target) || !taken.has(target))) {
          taken.add(target);
          return target as Target;
        }
      }
    }
    const field = fields.find((f) => clean(f.name) === h);
    if (field && !taken.has(field.id)) {
      taken.add(field.id);
      return `cf:${field.id}`;
    }
    return '' as Target;
  });
}

function cellText(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (value instanceof Date) {
    // Date cells hold a calendar day; read it in UTC so time zones can't shift it.
    return value.toISOString().slice(0, 10);
  }
  return String(value).trim();
}

/** Every sheet of the file as text, CSV files as one sheet. */
export async function readFile(file: File): Promise<Sheet[]> {
  const name = file.name.toLowerCase();
  if (name.endsWith('.xlsx')) {
    const { default: readXlsxFile } = await import('read-excel-file/browser');
    const sheets = await readXlsxFile(file);
    return sheets.map((s) => ({ name: s.sheet, rows: s.data.map((row) => row.map(cellText)) }));
  }
  if (name.endsWith('.xls') || name.endsWith('.xlsm')) {
    throw new Error('Save the file as .xlsx or .csv first (older Excel formats are not supported).');
  }
  const { default: Papa } = await import('papaparse');
  const text = await file.text();
  const parsed = Papa.parse<string[]>(text.charCodeAt(0) === 0xfeff ? text.slice(1) : text, {
    skipEmptyLines: 'greedy',
  });
  return [{ name: file.name, rows: parsed.data.map((row) => row.map(cellText)) }];
}

/** Day/month or month/day, from values like 15/10/2026 (null when every value fits both). */
export function detectDateFormat(values: string[]): DateFormat | null {
  let dmy = false;
  let mdy = false;
  for (const v of values) {
    const m = /^(\d{1,2})[/.-](\d{1,2})[/.-]\d{2,4}$/.exec(v.trim());
    if (!m) continue;
    if (Number(m[1]) > 12) dmy = true;
    if (Number(m[2]) > 12) mdy = true;
  }
  if (dmy !== mdy) return dmy ? 'dmy' : 'mdy';
  return null;
}

export function needsDateFormat(values: string[]): boolean {
  return values.some((v) => /^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$/.test(v.trim()));
}

/** Rows for the API. ``first`` is the file's row number of the first data row (the header is 1). */
export function buildRows(rows: string[][], mapping: Target[], first = 2): ImportRow[] {
  return rows
    .map((cells, i): ImportRow | null => {
      if (cells.every((c) => !c)) return null;
      const row: ImportRow = { row: first + i, comments: [], links: [], custom_fields: {} };
      mapping.forEach((target, col) => {
        const value = cells[col] ?? '';
        if (!target) return;
        if (target.startsWith('cf:')) {
          row.custom_fields![target.slice(3)] = value;
        } else if (target === 'comments') {
          if (value) row.comments!.push(value);
        } else if (target === 'links') {
          row.links!.push(...value.split(/[\s,]+/).filter(Boolean));
        } else {
          (row as Record<string, unknown>)[target] = value;
        }
      });
      return row;
    })
    .filter((r): r is ImportRow => r !== null);
}

/** Distinct non-empty values of the columns mapped to ``target`` (for status and priority choices). */
export function distinct(rows: string[][], mapping: Target[], target: Target, limit = 50): string[] {
  const col = mapping.indexOf(target);
  if (col < 0) return [];
  const seen = new Map<string, string>();
  for (const r of rows) {
    const v = (r[col] ?? '').trim();
    if (v && !seen.has(v.toLowerCase())) seen.set(v.toLowerCase(), v);
    if (seen.size >= limit) break;
  }
  return [...seen.values()];
}

const PRIORITY_WORDS: Record<string, string[]> = {
  urgent: ['urgent', 'critical', 'highest', 'blocker', 'p0', 'expedite'],
  high: ['high', 'major', 'important', 'p1', 'fixed date'],
  medium: ['medium', 'normal', 'moderate', 'p2', 'standard'],
  low: ['low', 'minor', 'lowest', 'trivial', 'p3', 'p4', 'intangible'],
};

export function guessPriority(value: string): string {
  const v = value.trim().toLowerCase();
  return Object.entries(PRIORITY_WORDS).find(([, words]) => words.includes(v))?.[0] ?? 'none';
}

const STATUS_WORDS: Record<string, string[]> = {
  backlog: ['backlog', 'icebox', 'later', 'ready'],
  todo: ['to do', 'todo', 'open', 'new', 'not started', 'planned', 'selected'],
  in_progress: ['in progress', 'doing', 'started', 'active', 'in review', 'review', 'testing', 'wip'],
  done: ['done', 'closed', 'complete', 'completed', 'finished', 'resolved', 'accepted'],
  cancelled: ['cancelled', 'canceled', 'rejected', "won't do", 'wont do', 'abandoned', 'discarded'],
};

/** The project status a value most likely means: same name, else a status of the same kind. */
export function guessStatus(
  value: string,
  statuses: { id: string; name: string; category: string }[],
): string {
  const v = value.trim().toLowerCase();
  const same = statuses.find((s) => s.name.toLowerCase() === v);
  if (same) return same.id;
  const category = Object.entries(STATUS_WORDS).find(([, words]) => words.includes(v))?.[0];
  return statuses.find((s) => s.category === category)?.id ?? '';
}
