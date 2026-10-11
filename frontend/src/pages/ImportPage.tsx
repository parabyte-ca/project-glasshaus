import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useId, useMemo, useState, type ChangeEvent } from 'react';
import { Link, useParams } from 'react-router';

import { api, unwrap, type Schemas } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { LoadError } from '../components/PageState';
import { Button, ErrorText, Field, GhostButton, linkClass, ScrollArea, Select } from '../components/ui';
import {
  buildRows,
  detectDateFormat,
  distinct,
  guessMapping,
  guessPriority,
  guessStatus,
  MAX_ROWS,
  MULTI,
  needsDateFormat,
  readFile,
  TARGETS,
  type DateFormat,
  type Sheet,
  type Source,
  type Target,
} from '../lib/importer';
import { usePageTitle } from '../lib/pageTitle';
import { toast } from '../lib/toast';
import { useUnsavedGuard } from '../lib/unsaved';
import { useProject } from '../lib/useProject';

type Result = Schemas['ImportResult'];

const PRIORITIES: [string, string][] = [
  ['none', 'None'],
  ['low', 'Low'],
  ['medium', 'Medium'],
  ['high', 'High'],
  ['urgent', 'Urgent'],
];
const DATE_FORMATS: [DateFormat, string][] = [
  ['dmy', 'Day/month/year (15/10/2026)'],
  ['mdy', 'Month/day/year (10/15/2026)'],
  ['ymd', 'Year-month-day (2026-10-15)'],
];
const td = 'border-b border-slate-200 px-2 py-1 align-top dark:border-slate-800';

function localeDateFormat(): DateFormat {
  return navigator.language === 'en-US' ? 'mdy' : 'dmy';
}

function Summary({ result }: { result: Result }) {
  const { user } = useAuth();
  const admin = user.org_role === 'owner' || user.org_role === 'admin';
  const verb = result.dry_run ? 'would be' : 'were';
  return (
    <section
      aria-labelledby="import-summary"
      className="flex flex-col gap-2 rounded-lg border border-slate-200 p-4 dark:border-slate-800"
    >
      <h2 id="import-summary" className="text-lg font-semibold">
        {result.dry_run ? 'Check' : 'Imported'}
      </h2>
      <p role="status">
        {result.created} new, {result.updated} updated and {result.unchanged} unchanged tasks {verb} imported
        {result.comments_added > 0 &&
          `, with ${result.comments_added} ${result.comments_added === 1 ? 'comment' : 'comments'}`}
        .{result.skipped > 0 && ` ${result.skipped} rows ${verb} skipped.`}
      </p>
      {result.warnings.map((w) => (
        <p key={w} className="text-sm text-amber-800 dark:text-amber-300">
          {w}
        </p>
      ))}
      {result.unmatched_people.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold">People not matched (their tasks stay unassigned)</h3>
          <ul className="list-disc pl-5 text-sm">
            {result.unmatched_people.map((p) => (
              <li key={p.value}>
                {p.value}: {p.reason} ({p.rows} {p.rows === 1 ? 'row' : 'rows'})
              </li>
            ))}
          </ul>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            {admin ? (
              <>
                Add them in{' '}
                <Link to="/admin?tab=people" className={linkClass}>
                  Admin › People
                </Link>{' '}
                or to the project, then import again: their tasks will be assigned.
              </>
            ) : (
              'Ask an administrator to add them, then import again: their tasks will be assigned.'
            )}
          </p>
        </div>
      )}
      {result.problems.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold">Rows with problems</h3>
          <ul className="max-h-60 overflow-auto text-sm">
            {result.problems.map((p, i) => (
              <li key={i}>
                Row {p.row}: {p.message}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

/** Import tasks into a project from a CSV or Excel file (including Nimble exports). */
export function ImportPage() {
  const { projectKey = '' } = useParams();
  const { project, fields } = useProject(projectKey);
  const p = project.data;
  usePageTitle(p ? `Import · ${p.name}` : 'Import');
  const queryClient = useQueryClient();
  const id = useId();
  const [source, setSource] = useState<Source>('spreadsheet');
  const [fileName, setFileName] = useState('');
  const [sheets, setSheets] = useState<Sheet[]>([]);
  const [sheetIndex, setSheetIndex] = useState(0);
  const [mapping, setMapping] = useState<Target[]>([]);
  const [dateFormat, setDateFormat] = useState<DateFormat>(localeDateFormat);
  const [statusMap, setStatusMap] = useState<Record<string, string>>({});
  const [priorityMap, setPriorityMap] = useState<Record<string, string>>({});
  const [readError, setReadError] = useState<unknown>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [done, setDone] = useState(false);
  const guard = useUnsavedGuard(sheets.length > 0 && !done);

  const sheet = sheets[sheetIndex];
  const headers = useMemo(() => sheet?.rows[0] ?? [], [sheet]);
  const body = useMemo(() => sheet?.rows.slice(1) ?? [], [sheet]);
  const statuses = useMemo(() => p?.statuses ?? [], [p]);
  const statusValues = distinct(body, mapping, 'status');
  const priorityValues = distinct(body, mapping, 'priority');
  const dateColumns = mapping.flatMap((t, col) =>
    t === 'start_date' || t === 'due_date' || fields.some((f) => f.type === 'date' && t === `cf:${f.id}`)
      ? [col]
      : [],
  );
  const dateValues = body.flatMap((r) => dateColumns.map((c) => r[c] ?? ''));
  const askDateFormat = needsDateFormat(dateValues);

  const reset = (next: Sheet[], index: number, src: Source) => {
    const s = next[index];
    const cols = s?.rows[0] ?? [];
    const guessed = guessMapping(cols, src, fields);
    setMapping(guessed);
    const rows = s?.rows.slice(1) ?? [];
    setStatusMap(
      Object.fromEntries(distinct(rows, guessed, 'status').map((v) => [v, guessStatus(v, statuses)])),
    );
    setPriorityMap(Object.fromEntries(distinct(rows, guessed, 'priority').map((v) => [v, guessPriority(v)])));
    const dates = rows.flatMap((r) => guessed.flatMap((t, c) => (t.endsWith('_date') ? [r[c] ?? ''] : [])));
    setDateFormat(detectDateFormat(dates) ?? localeDateFormat());
    setResult(null);
    setDone(false);
  };

  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    setReadError(null);
    if (!file) return;
    try {
      const read = (await readFile(file)).filter((s) => s.rows.length > 0);
      if (read.length === 0) throw new Error('The file has no rows.');
      setFileName(file.name);
      setSheets(read);
      setSheetIndex(0);
      reset(read, 0, source);
    } catch (err) {
      setSheets([]);
      setReadError(err instanceof Error ? err : new Error(String(err)));
    }
  };

  const setTarget = (col: number, target: Target) => {
    // Most fields take one column: picking it for another column frees the first.
    const next = mapping.map((t, i) =>
      i === col ? target : target && !MULTI.has(target) && t === target ? ('' as Target) : t,
    );
    setMapping(next);
    setResult(null);
    if (target === 'status')
      setStatusMap(
        Object.fromEntries(distinct(body, next, 'status').map((v) => [v, guessStatus(v, statuses)])),
      );
    if (target === 'priority')
      setPriorityMap(Object.fromEntries(distinct(body, next, 'priority').map((v) => [v, guessPriority(v)])));
  };

  const mapped = [...new Set(mapping.filter(Boolean))];
  const rows = useMemo(() => buildRows(body, mapping), [body, mapping]);
  const tooMany = rows.length > MAX_ROWS;
  const run = useMutation({
    mutationFn: (dryRun: boolean) =>
      unwrap(
        api.POST('/api/v1/projects/{project_id}/import', {
          params: { path: { project_id: p!.id } },
          body: {
            source,
            file_name: fileName,
            fields: mapped,
            date_format: askDateFormat ? dateFormat : 'auto',
            status_map: Object.fromEntries(
              Object.entries(statusMap)
                .filter(([, v]) => v)
                .map(([k, v]) => [k.toLowerCase(), v]),
            ),
            priority_map: Object.fromEntries(
              Object.entries(priorityMap).map(([k, v]) => [k.toLowerCase(), v as Schemas['Priority']]),
            ),
            rows,
            dry_run: dryRun,
          },
        }),
      ),
    onSuccess: async (r) => {
      setResult(r);
      if (!r.dry_run) {
        setDone(true);
        toast(`Imported into ${p!.name}: ${r.created} new, ${r.updated} updated.`);
        await queryClient.invalidateQueries({ queryKey: ['tasks', p!.id] });
      }
    },
  });

  if (project.isError)
    return <LoadError error={project.error} what="project" onRetry={() => void project.refetch()} />;
  if (!p) return <p role="status">Loading…</p>;
  if (p.my_role !== 'admin' && p.my_role !== 'editor')
    return (
      <p>
        Only project editors can import tasks.{' '}
        <Link to={`/projects/${p.key}`} className={linkClass}>
          Back to {p.name}
        </Link>
      </p>
    );

  return (
    <div className="flex max-w-5xl flex-col gap-6">
      <div>
        <Link to={`/projects/${p.key}`} className={`text-sm ${linkClass}`}>
          ← {p.name}
        </Link>
        <h1 className="text-2xl font-bold">Import tasks</h1>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Bring tasks into {p.name} from a CSV or Excel (.xlsx) file, such as an export from Nimble or another
          tool. Owners are matched by email. With an ID column, importing the file again updates the same
          tasks instead of adding them twice. Imported tasks don't notify anyone.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-4">
        <Field label="Exported from" id={`${id}-src`}>
          <Select
            id={`${id}-src`}
            value={source}
            onChange={(e) => {
              const next = e.target.value as Source;
              setSource(next);
              if (sheets.length) reset(sheets, sheetIndex, next);
            }}
          >
            <option value="spreadsheet">A spreadsheet (CSV or Excel)</option>
            <option value="nimble">Nimble (work item export)</option>
          </Select>
        </Field>
        <Field label="File" id={`${id}-file`}>
          <input
            id={`${id}-file`}
            type="file"
            accept=".csv,.xlsx,.txt,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(e) => void onFile(e)}
            className="text-sm"
          />
        </Field>
        {sheets.length > 1 && (
          <Field label="Sheet" id={`${id}-sheet`}>
            <Select
              id={`${id}-sheet`}
              value={sheetIndex}
              onChange={(e) => {
                const i = Number(e.target.value);
                setSheetIndex(i);
                reset(sheets, i, source);
              }}
            >
              {sheets.map((s, i) => (
                <option key={s.name} value={i}>
                  {s.name}
                </option>
              ))}
            </Select>
          </Field>
        )}
      </div>
      <ErrorText error={readError} />
      {source === 'nimble' && (
        <p className="text-sm text-slate-600 dark:text-slate-400">
          In Nimble, open the work items list, choose Export and pick all field content. Save as .xlsx or
          .csv.
        </p>
      )}

      {sheet && (
        <section aria-labelledby={`${id}-cols`} className="flex flex-col gap-3">
          <h2 id={`${id}-cols`} className="text-lg font-semibold">
            Columns ({rows.length} {rows.length === 1 ? 'row' : 'rows'})
          </h2>
          <ScrollArea label="Columns in the file">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left">
                  <th className={td}>Column</th>
                  <th className={td}>Example</th>
                  <th className={td}>Import as</th>
                </tr>
              </thead>
              <tbody>
                {headers.map((h, col) => (
                  <tr key={col}>
                    <td className={`${td} font-medium`}>{h || `Column ${col + 1}`}</td>
                    <td className={`${td} max-w-xs truncate text-slate-600 dark:text-slate-400`}>
                      {body.find((r) => r[col])?.[col] ?? ''}
                    </td>
                    <td className={td}>
                      <Select
                        aria-label={`Import ${h || `column ${col + 1}`} as`}
                        value={mapping[col] ?? ''}
                        onChange={(e) => setTarget(col, e.target.value as Target)}
                      >
                        <option value="">Don't import</option>
                        {TARGETS.map((t) => (
                          <option key={t.key} value={t.key}>
                            {t.label}
                          </option>
                        ))}
                        {fields.map((f) => (
                          <option key={f.id} value={`cf:${f.id}`}>
                            {f.name} (custom field)
                          </option>
                        ))}
                      </Select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollArea>
          {!mapping.includes('title') && (
            <p className="text-sm text-amber-800 dark:text-amber-300">
              Choose the column with each task's title.
            </p>
          )}
          {mapping.includes('title') && !mapping.includes('external_id') && (
            <p className="text-sm text-amber-800 dark:text-amber-300">
              Without an ID column, importing this file again adds the tasks again.
            </p>
          )}

          {askDateFormat && (
            <Field label="Dates in this file are written" id={`${id}-dates`}>
              <Select
                id={`${id}-dates`}
                value={dateFormat}
                onChange={(e) => setDateFormat(e.target.value as DateFormat)}
              >
                {DATE_FORMATS.map(([v, label]) => (
                  <option key={v} value={v}>
                    {label}
                  </option>
                ))}
              </Select>
            </Field>
          )}

          {statusValues.length > 0 && (
            <fieldset className="flex flex-col gap-2">
              <legend className="font-semibold">Statuses</legend>
              {statusValues.map((v) => (
                <label key={v} className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="min-w-40">{v}</span>→
                  <Select
                    value={statusMap[v] ?? ''}
                    onChange={(e) => setStatusMap((m) => ({ ...m, [v]: e.target.value }))}
                  >
                    <option value="">The first “to do” status</option>
                    {statuses.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </Select>
                </label>
              ))}
            </fieldset>
          )}

          {priorityValues.length > 0 && (
            <fieldset className="flex flex-col gap-2">
              <legend className="font-semibold">Priorities</legend>
              {priorityValues.map((v) => (
                <label key={v} className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="min-w-40">{v}</span>→
                  <Select
                    value={priorityMap[v] ?? 'none'}
                    onChange={(e) => setPriorityMap((m) => ({ ...m, [v]: e.target.value }))}
                  >
                    {PRIORITIES.map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </Select>
                </label>
              ))}
            </fieldset>
          )}

          {tooMany && (
            <p role="alert" className="text-sm text-red-700 dark:text-red-400">
              The file has {rows.length} rows; split it into files of at most {MAX_ROWS.toLocaleString()}{' '}
              rows.
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <GhostButton
              disabled={!mapping.includes('title') || tooMany || run.isPending || done}
              aria-busy={run.isPending && run.variables === true}
              onClick={() => run.mutate(true)}
            >
              {run.isPending && run.variables === true ? 'Checking…' : 'Check'}
            </GhostButton>
            <Button
              disabled={!mapping.includes('title') || tooMany || run.isPending || done}
              aria-busy={run.isPending && run.variables === false}
              onClick={() => run.mutate(false)}
            >
              {run.isPending && run.variables === false
                ? 'Importing…'
                : `Import ${rows.length} ${rows.length === 1 ? 'row' : 'rows'}`}
            </Button>
            {done && (
              <Link
                to={`/projects/${p.key}`}
                onClick={() => guard.allowNext()}
                className={`self-center text-sm ${linkClass}`}
              >
                Open {p.name}
              </Link>
            )}
          </div>
          <ErrorText error={run.error} />
        </section>
      )}

      {result && <Summary result={result} />}
    </div>
  );
}
