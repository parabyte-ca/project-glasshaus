import type { ReportResult } from '../api/client';
import { formatValue, type Chart } from '../lib/reportMeta';
import { LineChart, type Series } from './charts';
import { ScrollArea } from './ui';

const MAX_SERIES = 6;

type Target = { value: number; good: 'up' | 'down' };

/** One number, optionally against a target (state shown with an icon and words, not colour alone). */
export function KpiValue({
  result,
  title,
  target,
}: {
  result: ReportResult;
  title: string;
  target?: Target;
}) {
  const column = result.columns.find((c) => c.kind === 'measure');
  const value = result.totals[0] ?? null;
  const met =
    target && value !== null
      ? target.good === 'down'
        ? value <= target.value
        : value >= target.value
      : null;
  return (
    <div className="flex flex-col gap-1">
      <p
        className="text-4xl font-bold tabular-nums"
        aria-label={`${title}: ${formatValue(value, column?.unit ?? 'count')}`}
      >
        {formatValue(value, column?.unit ?? 'count')}
      </p>
      {column && <p className="text-sm text-slate-600 dark:text-slate-400">{column.label}</p>}
      {target && met !== null && (
        <p
          className={`flex items-center gap-1 text-sm font-medium ${met ? 'text-green-800 dark:text-green-400' : 'text-red-700 dark:text-red-400'}`}
        >
          <span aria-hidden="true">{met ? '✓' : '!'}</span>
          {met ? 'On target' : 'Off target'} (target {target.good === 'down' ? 'at most' : 'at least'}{' '}
          {formatValue(target.value, column?.unit ?? 'count')})
        </p>
      )}
    </div>
  );
}

export function ReportTable({ result, caption }: { result: ReportResult; caption: string }) {
  const dims = result.columns.filter((c) => c.kind === 'dimension');
  const measures = result.columns.filter((c) => c.kind === 'measure');
  return (
    <ScrollArea label={`${caption} (table)`} className="max-h-[32rem] overflow-auto">
      <table className="w-full border-collapse text-left text-sm tabular-nums">
        <caption className="sr-only">{caption}</caption>
        <thead className="sticky top-0 bg-white dark:bg-slate-950">
          <tr className="border-b border-slate-200 dark:border-slate-800">
            {result.columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={`px-2 py-1.5 font-medium ${c.kind === 'measure' ? 'text-right' : ''}`}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, i) => (
            <tr key={i} className="border-b border-slate-100 dark:border-slate-800/60">
              {row.labels.map((label, j) => (
                <td key={j} className="px-2 py-1.5">
                  {label}
                </td>
              ))}
              {row.values.map((v, j) => (
                <td key={j} className="px-2 py-1.5 text-right">
                  {formatValue(v, measures[j]!.unit)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="font-semibold">
            {dims.length > 0 && (
              <th scope="row" colSpan={dims.length} className="px-2 py-1.5">
                Total
              </th>
            )}
            {result.totals.map((v, j) => (
              <td key={j} className="px-2 py-1.5 text-right">
                {formatValue(v, measures[j]!.unit)}
              </td>
            ))}
          </tr>
        </tfoot>
      </table>
    </ScrollArea>
  );
}

/**
 * Horizontal bars, one per group, each labelled with its name and value (categories such as
 * projects or people have long names; every bar keeps its label and the value is text, not only
 * length). Negative values are not possible in these measures.
 */
function BarList({ result, title }: { result: ReportResult; title: string }) {
  const measure = result.columns.find((c) => c.kind === 'measure');
  const values = result.rows.map((r) => r.values[0] ?? 0);
  const max = Math.max(...values, 0) || 1;
  return (
    <figure className="flex flex-col gap-1">
      <figcaption className="text-xs text-slate-600 dark:text-slate-400">{measure?.label}</figcaption>
      <ul aria-label={title} className="flex flex-col gap-1.5">
        {result.rows.map((row, i) => (
          <li key={i} className="grid grid-cols-[minmax(6rem,14rem)_1fr_auto] items-center gap-2 text-sm">
            <span className="truncate" title={row.labels.join(' · ')}>
              {row.labels.join(' · ')}
            </span>
            <span aria-hidden="true" className="h-3 rounded-r bg-slate-100 dark:bg-slate-800">
              <span
                className="block h-3 rounded-r"
                style={{
                  width: `${Math.max((values[i]! / max) * 100, values[i]! > 0 ? 1 : 0)}%`,
                  background: 'var(--series-1)',
                }}
              />
            </span>
            <span className="text-right tabular-nums">
              {formatValue(row.values[0], measure?.unit ?? 'count')}
            </span>
          </li>
        ))}
      </ul>
    </figure>
  );
}

/** Lines: the first grouping along the x axis, the second (if any) as up to six series. */
function lineSeries(result: ReportResult): { labels: string[]; series: Series[]; hidden: number } {
  const xs: string[] = [];
  const seen = new Set<string>();
  for (const row of result.rows) {
    const x = row.labels[0] ?? '';
    if (!seen.has(x)) {
      seen.add(x);
      xs.push(x);
    }
  }
  const twoDims = result.columns.filter((c) => c.kind === 'dimension').length > 1;
  const groups = new Map<string, Map<string, number>>();
  for (const row of result.rows) {
    const name = twoDims
      ? (row.labels[1] ?? '')
      : (result.columns.find((c) => c.kind === 'measure')?.label ?? '');
    const values = groups.get(name) ?? new Map<string, number>();
    values.set(row.labels[0] ?? '', row.values[0] ?? 0);
    groups.set(name, values);
  }
  // Keep the series with the largest totals; colours follow that fixed order.
  const ranked = [...groups.entries()].sort(
    (a, b) => [...b[1].values()].reduce((s, v) => s + v, 0) - [...a[1].values()].reduce((s, v) => s + v, 0),
  );
  const series = ranked.slice(0, MAX_SERIES).map(([name, values], i) => ({
    name,
    color: `var(--series-${i + 1})`,
    values: xs.map((x) => values.get(x) ?? 0),
  }));
  return { labels: xs, series, hidden: Math.max(ranked.length - MAX_SERIES, 0) };
}

export function ReportView({
  result,
  chart,
  title,
  target,
}: {
  result: ReportResult;
  chart: Chart;
  title: string;
  target?: Target;
}) {
  const dims = result.columns.filter((c) => c.kind === 'dimension');
  const note = result.truncated
    ? `Showing ${result.rows.length} of ${result.total_groups} groups; totals include all of them.`
    : null;
  let body;
  if (chart === 'kpi' || dims.length === 0) {
    body = <KpiValue result={result} title={title} target={target} />;
  } else if (result.rows.length === 0) {
    body = <p className="text-sm text-slate-600 dark:text-slate-400">Nothing matches these filters.</p>;
  } else if (chart === 'bar' || (chart === 'line' && new Set(result.rows.map((r) => r.labels[0])).size < 2)) {
    // A line needs at least two points; one point reads better as a bar.
    body = <BarList result={result} title={title} />;
  } else if (chart === 'line') {
    const { labels, series, hidden } = lineSeries(result);
    body = (
      <>
        <LineChart title={title} labels={labels} series={series} />
        {hidden > 0 && (
          <p className="text-xs text-slate-600 dark:text-slate-400">
            The {MAX_SERIES} largest of {MAX_SERIES + hidden} series are drawn; the full table has them all.
          </p>
        )}
      </>
    );
  } else {
    body = <ReportTable result={result} caption={title} />;
  }
  return (
    <div className="flex flex-col gap-2">
      {body}
      {(chart === 'bar' || chart === 'line') && dims.length > 0 && result.rows.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-slate-600 dark:text-slate-400">
            Full table
            {result.columns.filter((c) => c.kind === 'measure').length > 1 ? ' (every measure)' : ''}
          </summary>
          <ReportTable result={result} caption={title} />
        </details>
      )}
      {note && <p className="text-xs text-slate-600 dark:text-slate-400">{note}</p>}
    </div>
  );
}
