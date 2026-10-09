import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';

import { ApiError, api, unwrap, type ReportOverrides, type SavedReport } from '../api/client';
import type { Chart } from '../lib/reportMeta';
import { ReportView } from './ReportView';
import { ErrorText, linkClass } from './ui';

/** A saved report on a dashboard, run with the viewer's access and the dashboard's filters. */
export function ReportTile({
  report,
  config,
  overrides,
}: {
  report: SavedReport | undefined;
  config: Record<string, unknown>;
  overrides: ReportOverrides | null;
}) {
  const id = typeof config.report_id === 'string' ? config.report_id : '';
  const result = useQuery({
    queryKey: ['report-run', id, overrides],
    enabled: !!id,
    queryFn: () =>
      unwrap(
        api.POST('/api/v1/reports/{report_id}/run', {
          params: { path: { report_id: id } },
          body: overrides ?? undefined,
        }),
      ),
  });
  if (result.error instanceof ApiError && result.error.status === 404) {
    return (
      <p className="text-sm text-slate-600 dark:text-slate-400">
        This report was deleted or is not shared with you.
      </p>
    );
  }
  if (result.error) return <ErrorText error={result.error} />;
  if (!result.data || !report) return <p role="status">Loading…</p>;
  const target =
    typeof config.target === 'number'
      ? { value: config.target, good: config.good === 'down' ? ('down' as const) : ('up' as const) }
      : undefined;
  return (
    <div className="flex flex-col gap-2">
      <ReportView
        result={result.data}
        chart={(report.definition.chart ?? 'table') as Chart}
        title={report.name}
        target={target}
      />
      <Link to={`/reports/${report.id}`} className={`self-start text-xs ${linkClass}`}>
        Open report
      </Link>
    </div>
  );
}
