import { useMutation } from '@tanstack/react-query';
import { useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router';

import { api, unwrap, type ReportDefinition } from '../api/client';
import type { Chart } from '../lib/reportMeta';
import { ReportView } from './ReportView';
import { Button, ErrorText, Field, Input, linkClass } from './ui';

/**
 * Ask a question in plain words; the assistant picks a saved report or builds a definition, the
 * server runs it with your access, and the answer is written from that table (shown alongside, so
 * the numbers can be checked). With `reportId` the question is about that saved report as it is.
 */
export function AskReports({ reportId, initial = '' }: { reportId?: string; initial?: string }) {
  const id = useId();
  const [question, setQuestion] = useState(initial);
  const ask = useMutation({
    mutationFn: (q: string) =>
      unwrap(api.POST('/api/v1/ai/reports', { body: { question: q, report_id: reportId ?? null } })),
  });
  // A question handed over from the command palette (?ask=…) runs once.
  const asked = useRef('');
  useEffect(() => {
    if (initial && asked.current !== initial) {
      asked.current = initial;
      ask.mutate(initial);
    }
  }, [initial, ask]);

  const a = ask.data;
  const title = a?.saved_report_name ?? 'Answer';
  return (
    <section aria-labelledby={`${id}-h`} className="flex flex-col gap-3">
      <h2 id={`${id}-h`} className="text-lg font-semibold">
        {reportId ? 'Ask about this report' : 'Ask a question'}
      </h2>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (question.trim()) ask.mutate(question.trim());
        }}
      >
        <div className="min-w-64 flex-1">
          <Field label="Question" id={`${id}-q`}>
            <Input
              id={`${id}-q`}
              value={question}
              maxLength={500}
              placeholder={
                reportId ? 'Which group stands out?' : 'Who has the most overdue tasks this month?'
              }
              onChange={(e) => setQuestion(e.target.value)}
            />
          </Field>
        </div>
        <Button type="submit" disabled={ask.isPending || !question.trim()}>
          {ask.isPending ? 'Asking…' : 'Ask'}
        </Button>
      </form>
      <ErrorText error={ask.error} />
      {a && (
        <article
          aria-live="polite"
          className="flex flex-col gap-3 rounded-lg border border-slate-200 p-4 dark:border-slate-800"
        >
          {/* Plain text on purpose: the answer may echo names from project data, so no links or images. */}
          <div className="flex flex-col gap-2 text-sm whitespace-pre-line">
            {a.answer.split(/\n{2,}/).map((p, i) => (
              <p key={i}>{p}</p>
            ))}
          </div>
          <p className="text-xs text-slate-600 dark:text-slate-400">
            {a.saved_report_name ? `From your saved report “${a.saved_report_name}”` : 'Report used'}
            {a.explanation ? `: ${a.explanation}` : ''}
            {a.result.date_from && a.result.date_to ? ` (${a.result.date_from} to ${a.result.date_to})` : ''}.
          </p>
          <ReportView result={a.result} chart={(a.definition.chart ?? 'table') as Chart} title={title} />
          <div className="flex flex-wrap gap-3 text-sm">
            {a.saved_report_id && !reportId ? (
              <Link to={`/reports/${a.saved_report_id}`} className={linkClass}>
                Open “{a.saved_report_name}”
              </Link>
            ) : (
              !reportId && (
                <Link
                  to="/reports/new"
                  state={{ definition: a.definition as ReportDefinition, name: a.question.slice(0, 120) }}
                  className={linkClass}
                >
                  Open in the report builder
                </Link>
              )
            )}
          </div>
          <p className="text-xs text-slate-600 dark:text-slate-400">
            Written by AI from the report above, which was run with your access. Check the numbers before you
            rely on them or share them.
          </p>
        </article>
      )}
    </section>
  );
}
